import os

import faiss
import numpy as np

from config import Config
from services.embedding_service import (
    generate_embeddings,
    generate_query_embedding,
    get_embedding_dimension,
)


def get_vector_folder() -> str:
    """Returns the absolute path to vector index storage directory."""
    folder = getattr(Config, "VECTOR_FOLDER", os.path.join(os.path.dirname(os.path.dirname(__file__)), "vector_indexes"))
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    return folder


def get_document_index_path(document_id: int) -> str:
    """Returns the file path for a document's FAISS index."""
    return os.path.join(get_vector_folder(), f"doc_{document_id}.index")


def is_document_indexed(document_id: int) -> bool:
    """Returns True if a FAISS index file exists for the given document ID."""
    return os.path.exists(get_document_index_path(document_id))


def build_and_save_index(document_id: int, chunks: list) -> tuple[str, int]:
    """
    Builds a FAISS IndexFlatIP with IndexIDMap for the given document's chunks
    and writes it to disk.

    Args:
        document_id: int
        chunks: list of DocumentChunk models or dicts with 'chunk_id' and 'chunk_text'

    Returns:
        tuple (index_file_path: str, indexed_count: int)
    """
    if not chunks:
        raise ValueError(f"No chunks provided to build vector index for document {document_id}")

    texts = []
    chunk_ids = []

    for idx, c in enumerate(chunks):
        c_id = getattr(c, "chunk_id", None)
        if c_id is None and isinstance(c, dict):
            c_id = c.get("chunk_id", idx + 1)
        elif c_id is None:
            c_id = idx + 1

        c_text = getattr(c, "chunk_text", None)
        if c_text is None and isinstance(c, dict):
            c_text = c.get("chunk_text", "")

        texts.append(c_text)
        chunk_ids.append(c_id)

    # Generate normalized embeddings
    vectors = generate_embeddings(texts)
    dim = get_embedding_dimension()

    # Create inner-product index wrapped in ID map
    base_index = faiss.IndexFlatIP(dim)
    index = faiss.IndexIDMap(base_index)

    ids_array = np.array(chunk_ids, dtype=np.int64)
    index.add_with_ids(vectors, ids_array)

    # Save to disk
    index_path = get_document_index_path(document_id)
    faiss.write_index(index, index_path)

    # Immediately cache in memory so subsequent searches avoid disk reads
    from services.cache_service import faiss_index_cache
    faiss_index_cache.set(str(document_id), index)

    return index_path, len(chunk_ids)


def load_document_index(document_id: int) -> faiss.Index | None:
    """Loads a document's FAISS index from cache or disk, or returns None if it doesn't exist."""
    from services.cache_service import faiss_index_cache
    cache_key = str(document_id)
    cached = faiss_index_cache.get(cache_key)
    if cached is not None:
        return cached

    path = get_document_index_path(document_id)
    if not os.path.exists(path):
        return None
    index = faiss.read_index(path)
    faiss_index_cache.set(cache_key, index)
    return index


def search_document_index(document_id: int, query: str | np.ndarray, top_k: int = 5) -> list[dict]:
    """
    Searches a document's FAISS index for chunks most relevant to the query.
    Accepts either a string query or a precomputed query embedding vector.

    Returns:
        list of dicts: [{'chunk_id': int, 'score': float, 'document_id': int}, ...]
    """
    index = load_document_index(document_id)
    if index is None or index.ntotal == 0:
        return []

    if isinstance(query, np.ndarray):
        query_vec = query
    else:
        query_vec = generate_query_embedding(query)

    k = min(top_k, index.ntotal)
    distances, indices = index.search(query_vec, k)

    results = []
    for score, chunk_id in zip(distances[0], indices[0]):
        if chunk_id != -1:  # FAISS uses -1 for unfilled slots
            results.append({
                "chunk_id": int(chunk_id),
                "score": float(score),
                "document_id": document_id
            })

    return results


def search_multi_document_indexes(document_ids: list[int], query: str | np.ndarray, top_k: int = 5) -> list[dict]:
    """
    Searches across multiple document FAISS indexes and returns top_k globally ranked chunks.
    Precomputes the query vector once to avoid redundant embedding model inferences.
    """
    if not document_ids:
        return []

    if isinstance(query, np.ndarray):
        query_vec = query
    else:
        query_vec = generate_query_embedding(query)

    all_results = []
    for doc_id in document_ids:
        doc_results = search_document_index(doc_id, query_vec, top_k=top_k)
        all_results.extend(doc_results)

    # Sort descending by similarity score
    all_results.sort(key=lambda r: r["score"], reverse=True)
    return all_results[:top_k]


def delete_document_index(document_id: int) -> bool:
    """Removes the FAISS index file for a document and purges it from cache if it exists."""
    from services.cache_service import faiss_index_cache
    faiss_index_cache.delete(str(document_id))

    path = get_document_index_path(document_id)
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False
