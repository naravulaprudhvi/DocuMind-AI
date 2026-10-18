from services.chunking import chunk_document_pages, clean_text, split_text_into_chunks
from services.ocr_service import is_ocr_available


def test_clean_text():
    raw = "Hello   world!  \n\n\n\nThis  is a   test."
    cleaned = clean_text(raw)
    assert "   " not in cleaned
    assert "\n\n\n" not in cleaned
    assert cleaned.startswith("Hello world!")


def test_split_text_into_chunks_short():
    short_text = "Short text under chunk size."
    chunks = split_text_into_chunks(short_text, chunk_size=500, chunk_overlap=100)
    assert len(chunks) == 1
    assert chunks[0] == short_text


def test_split_text_into_chunks_long():
    long_text = "Sentence one. " * 50  # ~700 characters
    chunks = split_text_into_chunks(long_text, chunk_size=200, chunk_overlap=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 250


def test_chunk_document_pages():
    pages = [
        {"page_number": 1, "text": "Page one content. " * 30},
        {"page_number": 2, "text": "Page two content. " * 30},
    ]
    chunks = chunk_document_pages(pages, chunk_size=300, chunk_overlap=50)
    assert len(chunks) > 0
    page_numbers = {c["page_number"] for c in chunks}
    assert page_numbers == {1, 2}
    assert all("chunk_text" in c for c in chunks)


def test_ocr_availability_check():
    # Should not throw exception
    available = is_ocr_available()
    assert isinstance(available, bool)
