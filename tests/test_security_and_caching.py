import io
import time

import pytest

from app import create_app
from extensions import db
from models.document import Document, DocumentChunk
from models.user import User
from routes.auth import check_rate_limit, record_failed_attempt, reset_login_attempts
from services.cache_service import (
    LRUCache,
    generate_query_cache_key,
)
from services.retrieval import retrieve_relevant_chunks


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


# ========================================================
# 1. Authentication Security & Brute-Force Rate Limiting
# ========================================================
def test_brute_force_rate_limiting():
    test_key = "attacker@example.com"
    reset_login_attempts(test_key)
    assert not check_rate_limit(test_key)

    # Simulate 5 consecutive failed attempts
    for _ in range(5):
        record_failed_attempt(test_key)

    # 6th attempt should be blocked
    assert check_rate_limit(test_key)

    # Reset clears lockout
    reset_login_attempts(test_key)
    assert not check_rate_limit(test_key)


def test_session_cookie_security_config(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] in ("Lax", "Strict")


# ========================================================
# 2. File Upload Security & Magic Bytes Verification
# ========================================================
def test_reject_fake_pdf_file_upload(client, app):
    # Register/login user
    email = "security_tester@example.com"
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(name="Sec Tester", email=email)
            user.set_password("SecurePassword@123")
            db.session.add(user)
            db.session.commit()

    client.post("/login", data={"email": email, "password": "SecurePassword@123"})

    # Try uploading an HTML file renamed as a .pdf with fake extension
    fake_pdf = (io.BytesIO(b"<html><script>alert('xss')</script></html>"), "exploit.pdf")
    res = client.post(
        "/documents",
        data={"pdf": fake_pdf},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"File verification failed" in res.data


# ========================================================
# 3. Multi-Tenant Document Isolation
# ========================================================
def test_multi_tenant_document_isolation(app):
    with app.app_context():
        # Setup User A and User B
        user_a = User.query.filter_by(email="tenant_a@example.com").first()
        if not user_a:
            user_a = User(name="User A", email="tenant_a@example.com")
            user_a.set_password("PassA123!")
            db.session.add(user_a)
            db.session.commit()

        user_b = User.query.filter_by(email="tenant_b@example.com").first()
        if not user_b:
            user_b = User(name="User B", email="tenant_b@example.com")
            user_b.set_password("PassB123!")
            db.session.add(user_b)
            db.session.commit()

        # Create Document for User A
        doc_a = Document(user_id=user_a.user_id, filename="user_a_confidential.pdf", file_path="dummy_a.pdf", status="ready")
        db.session.add(doc_a)
        db.session.commit()

        chunk_a = DocumentChunk(document_id=doc_a.document_id, page_number=1, chunk_text="Top secret project codename Prometheus.")
        db.session.add(chunk_a)
        db.session.commit()

        # User B queries vector retrieval targeting User A's document
        retrieved_by_b = retrieve_relevant_chunks(
            user_id=user_b.user_id,
            query="Prometheus",
            document_ids=[doc_a.document_id],
        )
        # MUST BE EMPTY - User B cannot retrieve User A's data
        assert len(retrieved_by_b) == 0


def test_cross_tenant_document_access_http(client, app):
    with app.app_context():
        user_a = User.query.filter_by(email="tenant_a@example.com").first()
        doc_a = Document.query.filter_by(user_id=user_a.user_id).first()
        doc_a_id = doc_a.document_id

    # Log in as User B
    client.post("/login", data={"email": "tenant_b@example.com", "password": "PassB123!"})

    # User B tries to view chunks of User A's document
    res_chunks = client.get(f"/documents/{doc_a_id}/chunks")
    assert res_chunks.status_code == 404

    # User B tries to view summary of User A's document
    res_summary = client.get(f"/documents/{doc_a_id}/summary")
    assert res_summary.status_code == 404

    # User B tries to delete User A's document
    res_del = client.post(f"/documents/{doc_a_id}/delete")
    assert res_del.status_code == 404


# ========================================================
# 4. In-Memory LRU & TTL Caching Service
# ========================================================
def test_lru_cache_operations():
    cache = LRUCache(capacity=3, default_ttl_seconds=2)
    cache.clear()

    # Set and get
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.set("k3", "v3")
    assert cache.get("k1") == "v1"
    assert cache.stats.hits == 1

    # Capacity eviction: adding k4 should evict k2 (since k1 was accessed)
    cache.set("k4", "v4")
    assert cache.get("k2") is None
    assert cache.stats.misses == 1

    # Expiry TTL
    cache.set("expiring_key", "temp", ttl_seconds=0.01)
    time.sleep(0.02)
    assert cache.get("expiring_key") is None


def test_query_cache_key_generation():
    k1 = generate_query_cache_key(user_id=1, query="What is RAG?", doc_ids=[2, 1])
    k2 = generate_query_cache_key(user_id=1, query="what is rag?", doc_ids=[1, 2])
    # Case insensitive query and sorted doc_ids should produce matching cache key
    assert k1 == k2
