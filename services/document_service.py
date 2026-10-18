from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from extensions import db
from models.document import Document, DocumentChunk, ProcessingJob
from services.chunking import chunk_document_pages
from services.pdf_processor import extract_pages_from_document
from services.vector_store import build_and_save_index, delete_document_index


def process_document_pipeline(document_id: int) -> tuple[bool, str, int]:
    """
    Executes the ingestion & vector indexing pipeline for a document:
    1. Updates status to 'processing'
    2. Extracts text from each page (with OCR fallback if applicable)
    3. Chunks the text preserving page references
    4. Persists chunks to the database
    5. Computes vector embeddings and builds FAISS index
    6. Updates vector_id on chunks and marks document as 'ready'

    Returns:
        (success: bool, message: str, chunk_count: int)
    """
    doc: Any = db.session.get(Document, document_id)
    if doc is None:
        return False, f"Document ID {document_id} not found", 0

    job: Any = ProcessingJob(document_id=doc.document_id, status="processing")
    db.session.add(job)
    doc.status = "processing"
    db.session.commit()

    try:
        # Extract pages using universal document extractor
        pages = extract_pages_from_document(doc.file_path)
        if not pages:
            raise ValueError("No readable pages could be extracted from the document.")

        # Chunk pages
        chunks_data = chunk_document_pages(pages)
        if not chunks_data:
            raise ValueError("The document contained no readable text or words.")

        # Remove any old chunks for this document if re-processing
        DocumentChunk.query.filter_by(document_id=doc.document_id).delete()
        delete_document_index(doc.document_id)

        # Save new chunks to DB with vector_id and flush to obtain autoincrement chunk_id
        chunk_models = []
        for idx, chunk_item in enumerate(chunks_data):
            db_chunk: Any = DocumentChunk(
                document_id=doc.document_id,
                page_number=chunk_item["page_number"],
                chunk_text=chunk_item["chunk_text"],
                vector_id=idx,
            )
            db.session.add(db_chunk)
            chunk_models.append(db_chunk)

        db.session.flush()

        # Build and save FAISS vector index
        build_and_save_index(doc.document_id, chunk_models)

        doc.status = "ready"
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        db.session.commit()

        return True, f"Extracted {len(pages)} pages, generated {len(chunks_data)} chunks, and built vector index.", len(chunks_data)

    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        doc.status = "failed"
        job.status = "failed"
        job.error_message = str(e)
        job.completed_at = datetime.now(UTC)
        db.session.commit()
        return False, str(e), 0
