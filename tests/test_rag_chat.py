from __future__ import annotations

from typing import Any

import fitz
import pytest

from app import create_app
from extensions import db
from models.conversation import Conversation
from models.document import Document
from models.message import Message
from models.user import User
from services.document_service import process_document_pipeline
from services.llm_service import generate_local_extractive_answer
from services.retrieval import build_rag_prompt, retrieve_relevant_chunks


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture(scope="module")
def user_and_doc(app):
    """Sets up a test user and processed document with vector index."""
    email = "rag_tester@example.com"
    with app.app_context():
        user: Any = User.query.filter_by(email=email).first()
        if not user:
            user = User(name="RAG Tester", email=email)
            user.set_password("Password123!")
            db.session.add(user)
            db.session.commit()

        # Create a test PDF
        doc_fitz = fitz.open()
        p1 = doc_fitz.new_page()
        p1.insert_text((50, 72), "Prudhvi is an artificial intelligence engineer skilled in Python, Flask, and FAISS vector databases.")
        p2 = doc_fitz.new_page()
        p2.insert_text((50, 72), "Education: Bachelor of Technology in Computer Science from Engineering College.")

        upload_dir = app.config["UPLOAD_FOLDER"]
        user_dir = f"{upload_dir}/{user.user_id}"
        import os
        os.makedirs(user_dir, exist_ok=True)
        pdf_path = f"{user_dir}/rag_test_resume.pdf"
        doc_fitz.save(pdf_path)
        doc_fitz.close()

        doc: Any = Document(
            user_id=user.user_id,
            filename="rag_test_resume.pdf",
            file_path=pdf_path,
            status="uploaded"
        )
        db.session.add(doc)
        db.session.commit()

        # Process document & build FAISS index
        process_document_pipeline(doc.document_id)

        user_id = user.user_id
        doc_id = doc.document_id

    return {"user_id": user_id, "email": email, "password": "Password123!", "doc_id": doc_id}


def test_retrieval_and_prompt_building(app, user_and_doc):
    with app.app_context():
        user_id = user_and_doc["user_id"]
        chunks = retrieve_relevant_chunks(user_id=user_id, query="Python and FAISS skills", top_k=2)
        assert len(chunks) > 0
        assert "Python" in chunks[0]["text"]
        assert chunks[0]["similarity_score"] > 0.3

        sys_prompt, user_prompt = build_rag_prompt("What are the skills?", chunks)
        assert "DocuMind AI" in sys_prompt
        assert "rag_test_resume.pdf" in user_prompt
        assert "What are the skills?" in user_prompt


def test_local_extractive_answer():
    sample_chunks = [
        {
            "chunk_id": 1,
            "document_name": "TestDoc.pdf",
            "page_number": 1,
            "text": "The candidate has 5 years of Python experience and built deep learning RAG pipelines.",
            "similarity_score": 0.85
        }
    ]
    answer = generate_local_extractive_answer("How many years of Python experience?", sample_chunks)
    assert "Python experience" in answer
    assert "TestDoc.pdf" in answer


def test_full_rag_chat_flow(client, app, user_and_doc):
    email = user_and_doc["email"]
    password = user_and_doc["password"]

    # 1. Login
    login_res = client.post("/login", data={"email": email, "password": password}, follow_redirects=True)
    assert login_res.status_code == 200

    # 2. View Chat page
    chat_page = client.get("/chat")
    assert chat_page.status_code == 200
    assert b"DocuMind RAG Assistant" in chat_page.data or b"Chat Workspace" in chat_page.data

    # 3. Create a new conversation thread
    new_conv_res = client.post("/chat/new", follow_redirects=True)
    assert new_conv_res.status_code == 200

    with app.app_context():
        conv = Conversation.query.filter_by(user_id=user_and_doc["user_id"]).order_by(Conversation.created_at.desc()).first()
        assert conv is not None
        conv_id = conv.conversation_id

    # 4. Send question via AJAX JSON API
    question = "What engineering degree and skills are listed?"
    json_res = client.post(
        f"/chat/{conv_id}/send",
        json={"question": question},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert json_res.status_code == 200
    data = json_res.get_json()
    assert data["success"] is True
    assert len(data["answer"]) > 10
    assert len(data["sources"]) > 0

    # 5. Verify database persistence
    with app.app_context():
        messages = Message.query.filter_by(conversation_id=conv_id).order_by(Message.created_at.asc()).all()
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == question
        assert messages[1].role == "assistant"
        assert len(messages[1].sources) > 0

    # 6. Delete conversation
    del_res = client.post(f"/chat/{conv_id}/delete", follow_redirects=True)
    assert del_res.status_code == 200

    with app.app_context():
        assert db.session.get(Conversation, conv_id) is None


def test_conversation_attached_document_memory(client, app, user_and_doc):
    """
    Verifies that once a document is attached to a conversation:
    1. It persists in conversation metadata.
    2. Subsequent messages without doc_ids automatically retain and use the attached document.
    3. Overview/skills questions ('which skills they have') retrieve relevant document chunks.
    """
    email = user_and_doc["email"]
    password = user_and_doc["password"]
    doc_id = user_and_doc["doc_id"]

    # Login
    client.post("/login", data={"email": email, "password": password}, follow_redirects=True)

    # Message 1: Attaching document explicitly
    res1 = client.post(
        "/chat/send",
        json={"question": "which skills they have", "doc_ids": [doc_id]},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert data1["success"] is True
    assert len(data1["sources"]) > 0
    conv_id = data1["conv_id"]

    # Verify conversation attached_doc_ids in DB
    with app.app_context():
        conv = db.session.get(Conversation, conv_id)
        assert conv is not None
        assert doc_id in conv.get_attached_doc_ids()

    # Message 2: Follow-up question WITHOUT passing doc_ids
    res2 = client.post(
        f"/chat/{conv_id}/send",
        json={"question": "What is their education background?"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["success"] is True
    # Should retain attached document and have grounded sources
    assert len(data2["sources"]) > 0

    # Cleanup
    client.post(f"/chat/{conv_id}/delete", follow_redirects=True)


def test_chat_without_documents_general_knowledge(client, app, user_and_doc):
    """
    Verifies that a user is allowed to chat directly with DocuMind AI
    without attaching any documents to ask basic information and general questions.
    """
    email = user_and_doc["email"]
    password = user_and_doc["password"]

    # Login
    client.post("/login", data={"email": email, "password": password}, follow_redirects=True)

    # 1. Send general question with empty doc_ids
    res = client.post(
        "/chat/send",
        json={"question": "What is Python and what is it used for?", "doc_ids": []},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert len(data["answer"]) > 20
    # No document sources should be attached for pure general chat
    assert len(data["sources"]) == 0
    conv_id = data["conv_id"]

    # 2. Send follow-up general question
    res2 = client.post(
        f"/chat/{conv_id}/send",
        json={"question": "Can you explain machine learning in one sentence?", "doc_ids": []},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["success"] is True
    assert len(data2["answer"]) > 10
    assert len(data2["sources"]) == 0

    # Cleanup
    client.post(f"/chat/{conv_id}/delete", follow_redirects=True)


