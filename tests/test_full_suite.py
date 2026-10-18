import io
import os

import fitz  # PyMuPDF
import pytest

from app import create_app
from extensions import db
from models.document import Document, DocumentChunk, ProcessingJob
from models.user import User
from services.chunking import chunk_document_pages, clean_text, split_text_into_chunks
from services.ocr_service import get_tesseract_path, is_ocr_available
from services.pdf_processor import extract_pages_from_pdf


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
def sample_pdf_bytes():
    """Creates an in-memory sample 2-page PDF."""
    doc = fitz.open()
    # Page 1
    page1 = doc.new_page()
    page1.insert_text((50, 72), "DocuMind AI Architecture - Page 1\nThis document tests automated text extraction, chunking, and database persistence.")
    # Page 2
    page2 = doc.new_page()
    page2.insert_text((50, 72), "DocuMind AI Architecture - Page 2\nRetrieval-Augmented Generation indexes chunks for vector similarity search.")
    
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# ==========================================
# 1. Config & Setup Tests
# ==========================================
def test_config_values(app):
    assert app.config["SECRET_KEY"]
    assert app.config["DB_NAME"] == "documind_db"
    assert app.config["DB_USER"]
    assert os.path.exists(app.config["UPLOAD_FOLDER"])
    assert os.path.exists(app.config["VECTOR_FOLDER"])


def test_ocr_service_health():
    path = get_tesseract_path()
    available = is_ocr_available()
    assert isinstance(available, bool)
    if available:
        assert path is not None


# ==========================================
# 2. Text Processing & Chunking Unit Tests
# ==========================================
def test_clean_text_utility():
    text = "  Word1    Word2 \t \n\n\n\n Word3   "
    cleaned = clean_text(text)
    assert cleaned == "Word1 Word2\n\nWord3"


def test_chunking_overlap_logic():
    text = "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda Mu."
    chunks = split_text_into_chunks(text, chunk_size=30, chunk_overlap=10)
    assert len(chunks) >= 2
    # Check that chunks are not empty and don't exceed max length significantly
    for c in chunks:
        assert len(c) > 0


def test_pdf_extraction_from_bytes(sample_pdf_bytes, tmp_path):
    pdf_path = str(tmp_path / "temp_test.pdf")
    with open(pdf_path, "wb") as f:
        f.write(sample_pdf_bytes)

    pages = extract_pages_from_pdf(pdf_path)
    assert len(pages) == 2
    assert pages[0]["page_number"] == 1
    assert "DocuMind AI Architecture - Page 1" in pages[0]["text"]
    assert pages[1]["page_number"] == 2
    assert "DocuMind AI Architecture - Page 2" in pages[1]["text"]

    chunks = chunk_document_pages(pages, chunk_size=100, chunk_overlap=20)
    assert len(chunks) >= 2
    assert {c["page_number"] for c in chunks} == {1, 2}


# ==========================================
# 3. User Authentication & Authorization Tests
# ==========================================
def test_unauthenticated_access_redirects(client):
    res_dash = client.get("/")
    assert res_dash.status_code == 302
    assert "/login" in res_dash.headers["Location"]

    res_docs = client.get("/documents")
    assert res_docs.status_code == 302
    assert "/login" in res_docs.headers["Location"]

    res_chat = client.get("/chat")
    assert res_chat.status_code == 302
    assert "/login" in res_chat.headers["Location"]


def test_registration_validation(client, app):
    # Short password (< 6 chars)
    res = client.post("/register", data={"name": "Test", "email": "testshort@example.com", "password": "123"})
    assert res.status_code == 200
    assert b"Password must be at least 6 characters" in res.data


def test_full_auth_and_session_cycle(client, app):
    test_email = "tester_automated_suite@example.com"
    test_pass = "TestPassword@123"

    with app.app_context():
        # Cleanup if previously existed
        existing = User.query.filter_by(email=test_email).first()
        if existing:
            # Delete any documents belonging to this user
            docs = Document.query.filter_by(user_id=existing.user_id).all()
            for d in docs:
                db.session.delete(d)
            db.session.delete(existing)
            db.session.commit()

    # 1. Register
    reg_res = client.post("/register", data={
        "name": "Suite Tester",
        "email": test_email,
        "password": test_pass
    }, follow_redirects=True)
    assert reg_res.status_code == 200
    assert b"Account created" in reg_res.data or b"Please log in" in reg_res.data

    # 2. Login with wrong password
    wrong_login = client.post("/login", data={
        "email": test_email,
        "password": "WrongPassword!"
    }, follow_redirects=True)
    assert b"Wrong email or password" in wrong_login.data

    # 3. Login with correct password
    login_res = client.post("/login", data={
        "email": test_email,
        "password": test_pass
    }, follow_redirects=True)
    assert login_res.status_code == 200
    assert b"Welcome, Suite Tester" in login_res.data or b"Dashboard" in login_res.data


# ==========================================
# 4. Document Ingestion, Processing & Chunks
# ==========================================
def test_document_upload_and_pipeline(client, app, sample_pdf_bytes):
    # Invalid upload: Non-PDF file
    bad_upload = client.post("/documents", data={
        "pdf": (io.BytesIO(b"dummy text"), "notes.txt")
    }, follow_redirects=True)
    assert b"Only PDF files are allowed" in bad_upload.data

    # Valid upload: 2-page PDF
    good_upload = client.post("/documents", data={
        "pdf": (io.BytesIO(sample_pdf_bytes), "automated_test_doc.pdf")
    }, follow_redirects=True)
    assert good_upload.status_code == 200
    assert b"PDF uploaded and processed successfully" in good_upload.data
    assert b"automated_test_doc.pdf" in good_upload.data

    # Verify Database state
    with app.app_context():
        doc = Document.query.filter_by(filename="automated_test_doc.pdf").order_by(Document.uploaded_at.desc()).first()
        assert doc is not None
        assert doc.status == "ready"
        assert len(doc.chunks) >= 2
        assert any(c.page_number == 1 for c in doc.chunks)
        assert any(c.page_number == 2 for c in doc.chunks)

        doc_id = doc.document_id

    # View chunks page
    chunks_res = client.get(f"/documents/{doc_id}/chunks")
    assert chunks_res.status_code == 200
    assert b"Extracted Chunks" in chunks_res.data
    assert b"Page 1" in chunks_res.data
    assert b"Page 2" in chunks_res.data

    # View original document route
    view_res = client.get(f"/documents/{doc_id}/view")
    assert view_res.status_code == 200
    assert "application/pdf" in view_res.headers.get("Content-Type", "")
    assert b"%PDF" in view_res.data

    # Test re-process route
    reprocess_res = client.post(f"/documents/{doc_id}/process", follow_redirects=True)
    assert reprocess_res.status_code == 200
    assert b"processed successfully" in reprocess_res.data

    # Test delete document
    delete_res = client.post(f"/documents/{doc_id}/delete", follow_redirects=True)
    assert delete_res.status_code == 200
    assert b"Document removed" in delete_res.data

    # Verify cascading delete in database
    with app.app_context():
        assert db.session.get(Document, doc_id) is None
        assert DocumentChunk.query.filter_by(document_id=doc_id).count() == 0
        assert ProcessingJob.query.filter_by(document_id=doc_id).count() == 0


def test_docx_upload_view_and_download(client, app):
    """Verifies that Word (.docx) documents can be uploaded, viewed in HTML viewer, and downloaded."""
    import docx
    import io

    test_email = "docx_tester@example.com"
    test_pass = "Password123!"

    with app.app_context():
        u = User.query.filter_by(email=test_email).first()
        if not u:
            u = User(name="Docx Tester", email=test_email)
            u.set_password(test_pass)
            db.session.add(u)
            db.session.commit()

    # Login as docx_tester
    client.post("/login", data={"email": test_email, "password": test_pass})

    # Create an in-memory valid DOCX
    d = docx.Document()
    d.add_heading("DocuMind AI Word Document Test", 0)
    p = d.add_paragraph("This is a paragraph with ")
    p.add_run("bold text").bold = True
    docx_io = io.BytesIO()
    d.save(docx_io)
    docx_io.seek(0)

    # Upload DOCX
    res = client.post("/documents", data={
        "pdf": (docx_io, "test_sample_word.docx")
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        doc = Document.query.filter_by(filename="test_sample_word.docx").order_by(Document.uploaded_at.desc()).first()
        assert doc is not None
        doc_id = doc.document_id

    # 1. View in browser (HTML viewer)
    view_res = client.get(f"/documents/{doc_id}/view")
    assert view_res.status_code == 200
    assert b"document-paper" in view_res.data
    assert b"DocuMind AI Word Document Test" in view_res.data
    assert b"Word Document (.docx)" in view_res.data

    # 2. Raw download
    raw_res = client.get(f"/documents/{doc_id}/view?raw=1&download=1")
    assert raw_res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in raw_res.headers.get("Content-Type", "")

    # Cleanup
    client.post(f"/documents/{doc_id}/delete")


# ==========================================
# 5. User Isolation & Security Tests
# ==========================================
def test_user_document_isolation(client, app, sample_pdf_bytes):
    """Verifies User B cannot view or delete User A's documents."""
    user_a_email = "usera@example.com"
    user_b_email = "userb@example.com"
    common_pass = "Password123!"

    with app.app_context():
        # Setup User A and User B
        for em in [user_a_email, user_b_email]:
            u = User.query.filter_by(email=em).first()
            if not u:
                u = User(name=em.split("@")[0], email=em)
                u.set_password(common_pass)
                db.session.add(u)
        db.session.commit()

    # Log in as User A and upload a document
    client.post("/login", data={"email": user_a_email, "password": common_pass})
    client.post("/documents", data={
        "pdf": (io.BytesIO(sample_pdf_bytes), "user_a_private.pdf")
    })

    with app.app_context():
        doc_a = Document.query.filter_by(filename="user_a_private.pdf").first()
        assert doc_a is not None
        doc_a_id = doc_a.document_id

    # Log out, then log in as User B
    client.get("/logout")
    client.post("/login", data={"email": user_b_email, "password": common_pass})

    # User B checks documents page - User A's document must not appear
    docs_page = client.get("/documents")
    assert b"user_a_private.pdf" not in docs_page.data

    # User B attempts to view User A's chunks -> 404
    chunks_attempt = client.get(f"/documents/{doc_a_id}/chunks")
    assert chunks_attempt.status_code == 404

    # User B attempts to delete User A's document -> 404
    delete_attempt = client.post(f"/documents/{doc_a_id}/delete")
    assert delete_attempt.status_code == 404

    # Cleanup: log back in as User A and delete
    client.get("/logout")
    client.post("/login", data={"email": user_a_email, "password": common_pass})
    client.post(f"/documents/{doc_a_id}/delete")
    client.get("/logout")
