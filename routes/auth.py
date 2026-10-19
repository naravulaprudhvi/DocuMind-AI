import time
from functools import wraps

from flask import (
    Blueprint,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from extensions import db
from models.document import Document
from models.user import User

auth_bp = Blueprint("auth", __name__)

_login_attempts: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 60.0


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "Your session has expired. Please refresh the page and log in again.",
                    "redirect": url_for("auth.login"),
                }), 401
            flash("Please log in first.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


@auth_bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id:
        try:
            g.user = db.session.get(User, user_id)
        except Exception:
            db.session.rollback()
            g.user = None
    else:
        g.user = None


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password")

        try:
            if not name or not email or len(password) < 6:
                flash("Fill all fields. Password must be at least 6 characters.", "danger")
            elif confirm_password is not None and password != confirm_password:
                flash("Passwords do not match. Please re-enter your password.", "danger")
            elif User.query.filter_by(email=email).first():
                flash("This email is already registered.", "danger")
            else:
                user = User(name=name, email=email)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                flash("Account created! Please log in.", "success")
                return redirect(url_for("auth.login"))
        except Exception as e:
            db.session.rollback()
            flash(f"Registration error: {e}", "danger")
    return render_template("register.html")


def check_rate_limit(key: str) -> bool:
    """Returns True if rate limited (locked out), False if allowed."""
    now = time.time()
    attempts = _login_attempts.get(key, [])
    # Keep attempts within the lockout window
    active_attempts = [t for t in attempts if now - t < LOCKOUT_WINDOW_SECONDS]
    _login_attempts[key] = active_attempts
    return len(active_attempts) >= MAX_LOGIN_ATTEMPTS


def record_failed_attempt(key: str) -> None:
    now = time.time()
    attempts = _login_attempts.get(key, [])
    attempts.append(now)
    _login_attempts[key] = attempts


def reset_login_attempts(key: str) -> None:
    _login_attempts.pop(key, None)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Brute-force protection check
        if check_rate_limit(email):
            flash("Too many failed login attempts. Please wait 60 seconds before trying again.", "danger")
            return render_template("login.html")

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            reset_login_attempts(email)
            session.clear()
            session["user_id"] = user.user_id
            return redirect(url_for("dashboard"))

        record_failed_attempt(email)
        flash("Wrong email or password.", "danger")
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = g.user
    if request.method == "POST":
        action = request.form.get("action", "update_name")

        if action == "update_name":
            name = request.form.get("name", "").strip()
            if not name:
                flash("Name cannot be empty.", "danger")
            else:
                user.name = name
                db.session.commit()
                flash("Profile name updated successfully!", "success")
            return redirect(url_for("auth.profile"))

        elif action == "update_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not user.check_password(current_password):
                flash("Current password is incorrect.", "danger")
            elif len(new_password) < 6:
                flash("New password must be at least 6 characters.", "danger")
            elif new_password != confirm_password:
                flash("New passwords do not match.", "danger")
            else:
                user.set_password(new_password)
                db.session.commit()
                flash("Password changed successfully!", "success")
            return redirect(url_for("auth.profile"))

        elif action == "update_preferences":
            session["pref_conciseness"] = request.form.get("pref_conciseness", "standard")
            session["pref_default_scope"] = request.form.get("pref_default_scope", "all")
            session["pref_pii_masking"] = (request.form.get("pref_pii_masking") == "on")
            flash("Workspace privacy & preferences saved successfully!", "success")
            return redirect(url_for("auth.profile"))

    # Fetch user usage stats
    doc_count = Document.query.filter_by(user_id=user.user_id).count()

    pref_conciseness = session.get("pref_conciseness", "standard")
    pref_default_scope = session.get("pref_default_scope", "all")
    pref_pii_masking = session.get("pref_pii_masking", True)

    from services.security_service import get_recent_security_events
    user_security_events = get_recent_security_events(user_id=user.user_id, limit=5)

    return render_template(
        "profile.html",
        user=user,
        doc_count=doc_count,
        pref_conciseness=pref_conciseness,
        pref_default_scope=pref_default_scope,
        pref_pii_masking=pref_pii_masking,
        security_events=user_security_events,
    )


@auth_bp.route("/profile/export-data", methods=["GET"])
@login_required
def export_data():
    """GDPR / CCPA Data Portability: Exports user profile, document catalog, chunks, and chat history as JSON."""
    import json
    from datetime import datetime, timezone
    from flask import Response
    from models.conversation import Conversation
    from models.document import DocumentChunk
    from models.message import Message
    from services.security_service import log_security_event

    user = g.user

    # Gather documents & chunks
    docs = Document.query.filter_by(user_id=user.user_id).all()
    docs_data = []
    for d in docs:
        chunks = DocumentChunk.query.filter_by(document_id=d.document_id).order_by(DocumentChunk.page_number.asc()).all()
        docs_data.append({
            "document_id": d.document_id,
            "filename": d.filename,
            "status": d.status,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "page_number": c.page_number,
                    "text": c.chunk_text,
                }
                for c in chunks
            ],
        })

    # Gather conversations & messages
    convs = Conversation.query.filter_by(user_id=user.user_id).all()
    convs_data = []
    for conv in convs:
        msgs = Message.query.filter_by(conversation_id=conv.conversation_id).order_by(Message.created_at.asc()).all()
        convs_data.append({
            "conversation_id": conv.conversation_id,
            "title": conv.title,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "messages": [
                {
                    "message_id": m.message_id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in msgs
            ],
        })

    export_bundle = {
        "export_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "application": "DocuMind AI",
            "compliance": "GDPR / CCPA Data Portability Export",
        },
        "user_profile": {
            "user_id": user.user_id,
            "name": user.name,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "documents": docs_data,
        "conversations": convs_data,
    }

    log_security_event("DATA_PORTABILITY_EXPORT", user.user_id, {"documents_count": len(docs), "conversations_count": len(convs)})

    json_bytes = json.dumps(export_bundle, indent=2, ensure_ascii=False).encode("utf-8")
    return Response(
        json_bytes,
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="documind_export_user_{user.user_id}.json"'
        },
    )


@auth_bp.route("/profile/delete-account", methods=["POST"])
@login_required
def delete_account():
    """GDPR / CCPA Right to be Forgotten: Permanently wipes account, files, vector indexes, and chat history."""
    import os
    import shutil
    from flask import current_app
    from models.document import DocumentChunk
    from models.message import MessageSource
    from services.cache_service import summary_cache
    from services.security_service import log_security_event
    from services.vector_store import delete_document_index

    user = g.user
    password = request.form.get("password", "")
    if not user.check_password(password):
        flash("Incorrect password. Account deletion aborted for security.", "danger")
        return redirect(url_for("auth.profile"))

    user_id = user.user_id

    # 1. Erase physical files from disk in sandboxed user folder
    user_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(user_id))
    if os.path.exists(user_dir):
        try:
            shutil.rmtree(user_dir)
        except OSError:
            pass

    # 2. Erase vector index files from disk and invalidate caches
    docs = Document.query.filter_by(user_id=user_id).all()
    for d in docs:
        delete_document_index(d.document_id)
        summary_cache.delete(f"doc_summary_{d.document_id}")

    # 3. Clean MessageSource foreign references before cascading
    all_chunk_ids = [
        c[0] for c in db.session.query(DocumentChunk.chunk_id)
        .join(Document, Document.document_id == DocumentChunk.document_id)
        .filter(Document.user_id == user_id)
        .all()
    ]
    if all_chunk_ids:
        MessageSource.query.filter(MessageSource.chunk_id.in_(all_chunk_ids)).delete(synchronize_session=False)

    log_security_event("ACCOUNT_PERMANENTLY_PURGED", user_id, {"email": user.email})

    # 4. Cascade delete user and all DB relationships
    db.session.delete(user)
    db.session.commit()

    session.clear()
    flash("Your account and all associated documents, vector embeddings, and chat history have been permanently erased.", "info")
    return redirect(url_for("auth.login"))

