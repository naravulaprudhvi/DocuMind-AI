import os

import numpy as np

from services.embedding_service import (
    generate_embeddings,
    generate_query_embedding,
    get_embedding_dimension,
)
from services.vector_store import (
    build_and_save_index,
    delete_document_index,
    is_document_indexed,
    search_document_index,
    search_multi_document_indexes,
)


def test_embedding_dimensions_and_normalization():
    texts = [
        "Machine learning models need vector representations.",
        "DocuMind AI enables intelligent PDF questioning."
    ]
    vectors = generate_embeddings(texts)
    assert vectors.shape == (2, get_embedding_dimension())
    assert vectors.dtype == np.float32

    # Verify L2 normalization (norm should be ~1.0)
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)

    # Test query embedding
    q_vec = generate_query_embedding("What is DocuMind?")
    assert q_vec.shape == (1, get_embedding_dimension())
    assert np.isclose(np.linalg.norm(q_vec[0]), 1.0, atol=1e-4)


def test_vector_indexing_and_search_lifecycle():
    test_doc_id = 9999
    chunks = [
        {"chunk_id": 9001, "chunk_text": "Python is a popular programming language for AI and web development."},
        {"chunk_id": 9002, "chunk_text": "FAISS is a library for fast dense vector similarity search."},
        {"chunk_id": 9003, "chunk_text": "The solar system contains eight planets orbiting the sun."}
    ]

    try:
        # 1. Build and save index
        index_path, count = build_and_save_index(test_doc_id, chunks)
        assert os.path.exists(index_path)
        assert count == 3
        assert is_document_indexed(test_doc_id)

        # 2. Search for AI / Python
        results = search_document_index(test_doc_id, "Python and artificial intelligence", top_k=2)
        assert len(results) == 2
        # Most relevant should be chunk 9001
        assert results[0]["chunk_id"] == 9001
        assert results[0]["score"] > 0.4
        assert results[0]["score"] > results[1]["score"]

        # 3. Search for astronomy
        astro_results = search_document_index(test_doc_id, "planets in space", top_k=1)
        assert len(astro_results) == 1
        assert astro_results[0]["chunk_id"] == 9003

        # 4. Multi-document search test
        multi_results = search_multi_document_indexes([test_doc_id], "fast vector database", top_k=1)
        assert len(multi_results) == 1
        assert multi_results[0]["chunk_id"] == 9002

    finally:
        # 5. Clean up
        deleted = delete_document_index(test_doc_id)
        assert deleted is True
        assert not is_document_indexed(test_doc_id)
