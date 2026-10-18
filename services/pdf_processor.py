from __future__ import annotations

import os

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # PyMuPDF fallback

from services.ocr_service import is_ocr_available, perform_ocr


def extract_pages_from_pdf(file_path: str, min_chars_for_ocr: int = 40) -> list[dict]:
    """
    Extracts text from each page of a PDF.
    If a page has fewer than `min_chars_for_ocr` characters and OCR is available,
    it renders the page as an image and uses OCR to extract text.

    Returns:
        list of dicts: [
            {
                "page_number": int (1-indexed),
                "text": str,
                "is_ocr": bool,
                "char_count": int
            },
            ...
        ]
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    pages = []
    doc = fitz.open(file_path)

    try:
        for idx, page in enumerate(doc):
            page_num = idx + 1
            text = page.get_text("text").strip()
            used_ocr = False

            # If text is too short and OCR is available, try OCR fallback
            if len(text) < min_chars_for_ocr and is_ocr_available():
                try:
                    # Render page to high-res pixmap (200 dpi)
                    pix = page.get_pixmap(dpi=200)
                    img_bytes = pix.tobytes("png")
                    ocr_text = perform_ocr(img_bytes)
                    if len(ocr_text) > len(text):
                        text = ocr_text
                        used_ocr = True
                except (RuntimeError, ValueError, OSError):
                    # If OCR fails, keep what we have
                    pass

            pages.append({
                "page_number": page_num,
                "text": text,
                "is_ocr": used_ocr,
                "char_count": len(text),
            })
    finally:
        doc.close()

    return pages


def extract_pages_from_docx(file_path: str) -> list[dict]:
    """
    Extracts text from a Microsoft Word document (.docx).
    Extracts body paragraphs, headings, and table cells, grouping into pages.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    import docx

    doc = docx.Document(file_path)
    content_blocks = []

    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            content_blocks.append(t)

    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                content_blocks.append(" | ".join(cells))

    # Paginate by ~400 words per virtual page
    pages = []
    current_block = []
    current_word_count = 0
    page_num = 1

    for block in content_blocks:
        current_block.append(block)
        current_word_count += len(block.split())
        if current_word_count >= 400:
            page_text = "\n\n".join(current_block)
            pages.append({
                "page_number": page_num,
                "text": page_text,
                "is_ocr": False,
                "char_count": len(page_text),
            })
            current_block = []
            current_word_count = 0
            page_num += 1

    if current_block:
        page_text = "\n\n".join(current_block)
        pages.append({
            "page_number": page_num,
            "text": page_text,
            "is_ocr": False,
            "char_count": len(page_text),
        })

    return pages


def extract_pages_from_text(file_path: str) -> list[dict]:
    """Extracts text from plain text or markdown files (.txt, .md)."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, encoding="utf-8", errors="ignore") as f:
        full_text = f.read().strip()

    if not full_text:
        return []

    # Divide by ~400 words per virtual page
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    pages = []
    current_block = []
    current_word_count = 0
    page_num = 1

    for p in paragraphs:
        current_block.append(p)
        current_word_count += len(p.split())
        if current_word_count >= 400:
            page_text = "\n\n".join(current_block)
            pages.append({
                "page_number": page_num,
                "text": page_text,
                "is_ocr": False,
                "char_count": len(page_text),
            })
            current_block = []
            current_word_count = 0
            page_num += 1

    if current_block:
        page_text = "\n\n".join(current_block)
        pages.append({
            "page_number": page_num,
            "text": page_text,
            "is_ocr": False,
            "char_count": len(page_text),
        })

    return pages


def extract_pages_from_document(file_path: str, min_chars_for_ocr: int = 40) -> list[dict]:
    """
    Universal document extractor that automatically delegates to the appropriate
    handler based on file extension (.pdf, .docx, .doc, .txt, .md).
    """
    ext = os.path.splitext(file_path.lower())[1]

    if ext == ".docx":
        return extract_pages_from_docx(file_path)
    if ext in (".txt", ".md", ".csv"):
        return extract_pages_from_text(file_path)
    if ext == ".pdf":
        return extract_pages_from_pdf(file_path, min_chars_for_ocr)

    # Fallback: attempt docx first, then pdf
    try:
        return extract_pages_from_docx(file_path)
    except Exception:  # noqa: BLE001
        return extract_pages_from_pdf(file_path, min_chars_for_ocr)
