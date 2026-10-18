from __future__ import annotations

from datetime import datetime, timedelta
import os
from typing import Any

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from sqlalchemy.orm import selectinload

from extensions import db
from models.conversation import Conversation
from models.document import Document, DocumentChunk
from models.message import Message, MessageSource
from routes.auth import login_required
from services.cache_service import generate_query_cache_key, query_response_cache
from services.llm_service import generate_rag_response
from services.retrieval import retrieve_relevant_chunks

chat_bp = Blueprint("chat", __name__)


def get_grouped_conversations(conversations: list[Conversation]) -> list[tuple[str, list[Conversation]]]:
    """
    Groups conversation threads into ChatGPT-style time buckets:
    'Today', 'Yesterday', 'Previous 7 Days', 'Previous 30 Days', 'Older'.
    """
    now = datetime.utcnow()
    today = now.date()
    yesterday = today - timedelta(days=1)
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)

    groups: list[tuple[str, list[Conversation]]] = [
        ("Today", []),
        ("Yesterday", []),
        ("Previous 7 Days", []),
        ("Previous 30 Days", []),
        ("Older", []),
    ]

    for c in conversations:
        if not c.created_at:
            groups[4][1].append(c)
            continue
        c_date = c.created_at.date()
        if c_date == today:
            groups[0][1].append(c)
        elif c_date == yesterday:
            groups[1][1].append(c)
        elif c_date > seven_days_ago:
            groups[2][1].append(c)
        elif c_date > thirty_days_ago:
            groups[3][1].append(c)
        else:
            groups[4][1].append(c)

    return [(title, items) for title, items in groups if items]


@chat_bp.route("/chat", methods=["GET"])
@login_required
def chat():
    user_id = session.get("user_id")

    # Fetch user's conversation threads
    conversations = (
        Conversation.query.filter_by(user_id=user_id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    grouped_conversations = get_grouped_conversations(conversations)

    # Fetch user's indexed documents
    ready_docs = (
        Document.query.filter_by(user_id=user_id, status="ready")
        .order_by(Document.uploaded_at.desc())
        .all()
    )

    # Determine active conversation (only set if explicitly requested via ?c=<id>)
    active_conv_id = request.args.get("c", type=int)
    active_conv = None

    if active_conv_id:
        active_conv = Conversation.query.filter_by(
            conversation_id=active_conv_id, user_id=user_id
        ).first()

    messages = []
    attached_docs = []
    if active_conv:
        messages = (
            Message.query.filter_by(conversation_id=active_conv.conversation_id)
            .options(
                selectinload(Message.sources)
                .selectinload(MessageSource.chunk)
                .selectinload(DocumentChunk.document)
            )
            .order_by(Message.created_at.asc(), Message.message_id.asc())
            .all()
        )
        attached_ids = active_conv.get_attached_doc_ids()
        if attached_ids:
            found_docs = (
                Document.query.filter(
                    Document.document_id.in_(attached_ids),
                    Document.user_id == user_id,
                    Document.status == "ready",
                )
                .order_by(Document.uploaded_at.desc())
                .all()
            )
            attached_docs = [{"id": d.document_id, "name": d.filename} for d in found_docs]

    has_gemini = bool(os.getenv("GEMINI_API_KEY"))

    return render_template(
        "chat.html",
        conversations=conversations,
        grouped_conversations=grouped_conversations,
        active_conv=active_conv,
        messages=messages,
        docs=ready_docs,
        attached_docs=attached_docs,
        has_gemini=has_gemini,
    )


@chat_bp.route("/chat/new", methods=["GET", "POST"])
@login_required
def new_chat():
    if request.method == "POST":
        user_id = session.get("user_id")
        conv: Any = Conversation(user_id=user_id, title="New Conversation")
        db.session.add(conv)
        db.session.commit()
        return redirect(url_for("chat.chat", c=conv.conversation_id))
    return redirect(url_for("chat.chat"))


@chat_bp.route("/chat/send", methods=["POST"])
@chat_bp.route("/chat/<int:conv_id>/send", methods=["POST"])
@login_required
def send_message(conv_id: int | None = None):
    user_id = session.get("user_id")

    # If this is a fresh conversation, create it now that the user sent their first message
    if not conv_id:
        conv: Any = Conversation(user_id=user_id, title="New chat")
        db.session.add(conv)
        db.session.commit()
    else:
        conv = Conversation.query.filter_by(
            conversation_id=conv_id, user_id=user_id
        ).first_or_404()

    is_json = request.is_json
    has_explicit_doc_selection = False
    doc_ids: list[int] = []

    if is_json:
        data = request.get_json() or {}
        question = data.get("question", "").strip()
        has_explicit_doc_selection = "doc_ids" in data or "document_ids" in data or "doc_id" in data
        raw_ids = data.get("doc_ids")
        if raw_ids is None and data.get("document_ids") is not None:
            raw_ids = data.get("document_ids")
        if not raw_ids and data.get("doc_id"):
            val = data.get("doc_id")
            raw_ids = val if isinstance(val, list) else [val]
        for d in (raw_ids or []):
            try:
                doc_ids.append(int(d))
            except (ValueError, TypeError):
                pass
    else:
        question = request.form.get("question", "").strip()
        has_explicit_doc_selection = "doc_ids" in request.form or "document_ids" in request.form or "doc_id" in request.form
        raw_ids = request.form.getlist("doc_ids", type=int) or request.form.getlist("document_ids", type=int)
        if not raw_ids and request.form.get("doc_id"):
            for part in str(request.form.get("doc_id")).split(","):
                try:
                    if part.strip():
                        raw_ids.append(int(part.strip()))
                except (ValueError, TypeError):
                    pass
        doc_ids = raw_ids

    # Conversation Document Memory & Explicit Selection:
    # If the user attaches/passes document(s), save them to this conversation.
    # If the user explicitly has no documents attached in a new chat or sends clear_docs, keep doc_ids empty.
    # Otherwise, if the conversation has previously attached documents, retain them.
    if doc_ids:
        conv.set_attached_doc_ids(doc_ids)
        db.session.commit()
    elif is_json and (data.get("clear_docs") or (has_explicit_doc_selection and not conv.get_attached_doc_ids())):
        # Explicit general chat without documents
        conv.set_attached_doc_ids([])
        db.session.commit()
        doc_ids = []
    else:
        conv_attached = conv.get_attached_doc_ids()
        if conv_attached:
            doc_ids = conv_attached

    if not question:
        if is_json:
            return jsonify({"error": "Question cannot be empty"}), 400
        flash("Please enter a question.", "warning")
        return redirect(url_for("chat.chat", c=conv_id))

    # Auto-title conversation if still default
    if conv.title in ("New Conversation", "New chat"):
        conv.title = (question[:32] + "...") if len(question) > 35 else question

    # 1. Immediately save User message so it is guaranteed to precede the assistant answer
    user_msg: Any = Message(
        conversation_id=conv.conversation_id,
        role="user",
        content=question,
    )
    db.session.add(user_msg)
    db.session.commit()

    cache_key = generate_query_cache_key(user_id, question, doc_ids if doc_ids else None)
    cached_entry = query_response_cache.get(cache_key)

    if cached_entry:
        answer, chunks = cached_entry
    else:
        # 2. Adaptive Document Retrieval:
        # When doc_ids is present, retrieve with gentle threshold and include overview chunks
        # if the query is an overview or broad question.
        chunks = []
        if doc_ids:
            chunks = retrieve_relevant_chunks(
                user_id=user_id,
                query=question,
                document_ids=doc_ids,
                top_k=5,
                min_score=0.20,
            )
        elif not has_explicit_doc_selection:
            # Fallback for automated tests where doc_ids was omitted
            chunks = retrieve_relevant_chunks(
                user_id=user_id,
                query=question,
                document_ids=None,
                top_k=5,
                min_score=0.20,
            )

        # 3. Fetch past conversation turns for memory context (exclude current user_msg)
        recent_msgs = (
            Message.query.filter(
                Message.conversation_id == conv.conversation_id,
                Message.message_id != user_msg.message_id,
            )
            .order_by(Message.created_at.desc(), Message.message_id.desc())
            .limit(6)
            .all()
        )
        chat_history = [
            {"role": m.role, "content": m.content}
            for m in reversed(recent_msgs)
        ]

        # Privacy Guard: Redact sensitive PII if user privacy shield is active
        from services.security_service import detect_prompt_injection, log_security_event, redact_pii
        if detect_prompt_injection(question):
            log_security_event("PROMPT_INJECTION_DEFUSED", user_id, {"preview": question[:60]})

        processed_chunks = chunks
        if session.get("pref_pii_masking", True):
            processed_chunks = []
            for c in chunks:
                sanitized_text, _ = redact_pii(c.get("text", ""))
                c_copy = dict(c)
                c_copy["text"] = sanitized_text
                processed_chunks.append(c_copy)

        # 4. Generate answer using RAG LLM engine
        answer = generate_rag_response(question, processed_chunks, chat_history)

        # Cache answer for repeated queries
        query_response_cache.set(cache_key, (answer, chunks))

    # 5. Save Assistant Message
    assistant_msg: Any = Message(
        conversation_id=conv.conversation_id,
        role="assistant",
        content=answer,
    )
    db.session.add(assistant_msg)
    db.session.flush()

    sources_data = []
    for c in chunks:
        src: Any = MessageSource(
            message_id=assistant_msg.message_id,
            chunk_id=c["chunk_id"],
            relevance_score=c["similarity_score"],
        )
        db.session.add(src)
        sources_data.append({
            "doc_name": c["document_name"],
            "document_id": c["document_id"],
            "page_number": c["page_number"],
            "chunk_id": c["chunk_id"],
            "score": c["similarity_score"],
            "snippet": c["text"][:180] + "...",
        })

    db.session.commit()

    if is_json:
        attached_list = []
        if doc_ids:
            for d in Document.query.filter(Document.document_id.in_(doc_ids)).all():
                attached_list.append({"id": d.document_id, "name": d.filename})
        return jsonify({
            "success": True,
            "answer": answer,
            "sources": sources_data,
            "conv_id": conv.conversation_id,
            "attached_docs": attached_list,
        })

    return redirect(url_for("chat.chat", c=conv.conversation_id))


@chat_bp.route("/chat/<int:conv_id>/delete", methods=["POST"])
@login_required
def delete_conversation(conv_id: int):
    user_id = session.get("user_id")
    conv = Conversation.query.filter_by(
        conversation_id=conv_id, user_id=user_id
    ).first_or_404()

    db.session.delete(conv)
    db.session.commit()
    flash("Conversation deleted.", "success")
    return redirect(url_for("chat.chat"))
