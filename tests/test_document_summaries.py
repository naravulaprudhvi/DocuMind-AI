from __future__ import annotations

from typing import Any

import pytest

from app import create_app
from extensions import db
from models.document import Document, DocumentChunk
from models.user import User
from routes.summaries import generate_document_summary


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def test_generate_document_summary():
    class DummyDoc:
        filename = "test_profile.pdf"

    class DummyChunk:
        def __init__(self, text):
            self.chunk_text = text

    chunks = [
        DummyChunk("Prudhvi is an engineer who developed advanced RAG software. He implemented high performance systems."),
        DummyChunk("Education: Bachelor of Technology. He managed technical deliverables and engineered scalable APIs.")
    ]
    summary = generate_document_summary(DummyDoc(), chunks)
    assert summary["word_count"] > 10
    assert summary["chunk_count"] == 2
    assert len(summary["overview"]) > 10
    assert len(summary["takeaways"]) > 0


def test_summary_routes(client, app):
    email = "eval_user@example.com"
    with app.app_context():
        user: Any = User.query.filter_by(email=email).first()
        if not user:
            user = User(name="Eval User", email=email)
            user.set_password("Password123!")
            db.session.add(user)
            db.session.commit()

        # Create dummy doc and chunk
        doc: Any = Document(user_id=user.user_id, filename="eval_doc.pdf", file_path="dummy.pdf", status="ready")
        db.session.add(doc)
        db.session.commit()

        chunk: Any = DocumentChunk(document_id=doc.document_id, page_number=1, chunk_text="This is evaluation content about machine learning.")
        db.session.add(chunk)
        db.session.commit()

        doc_id = doc.document_id

    # Login
    client.post("/login", data={"email": email, "password": "Password123!"})

    # 1. View Summary
    summary_res = client.get(f"/documents/{doc_id}/summary")
    assert summary_res.status_code == 200
    assert b"Executive Overview" in summary_res.data
    assert b"eval_doc.pdf" in summary_res.data

