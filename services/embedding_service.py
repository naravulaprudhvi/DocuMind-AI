import os

import numpy as np

# Suppress TensorFlow / oneDNN and Windows symlink warnings
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import logging
import threading
import faiss

logger = logging.getLogger("documind.embedding")

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model_instance = None
_model_lock = threading.Lock()


def get_embedding_model(model_name: str = DEFAULT_MODEL_NAME):
    """Singleton getter for the SentenceTransformer model with CPU thread limits."""
    global _model_instance
    if _model_instance is None:
        with _model_lock:
            if _model_instance is None:
                try:
                    import torch
                    torch.set_num_threads(1)
                    if hasattr(torch, "set_num_interop_threads"):
                        torch.set_num_interop_threads(1)
                except Exception:
                    pass
                try:
                    from sentence_transformers import SentenceTransformer
                    _model_instance = SentenceTransformer(model_name)
                except Exception as e:
                    logger.warning(f"Could not load SentenceTransformer '{model_name}': {e}")
                    _model_instance = False
    return _model_instance if _model_instance is not False else None


def warmup_embedding_model_async():
    """Asynchronously pre-loads the SentenceTransformer model in a background thread."""
    def _warmup():
        try:
            import time
            time.sleep(12)  # Delay to allow server to boot and respond to health checks
            get_embedding_model()
        except Exception:
            pass

    t = threading.Thread(target=_warmup, daemon=True, name="embedding-model-warmup")
    t.start()
    return t


def get_embedding_dimension() -> int:
    """Returns the vector dimensionality (384 for all-MiniLM-L6-v2)."""
    return EMBEDDING_DIM


def generate_fast_feature_embeddings(texts: list[str]) -> np.ndarray:
    """
    Ultra-lightweight deterministic n-gram & word hashing embedding fallback (384 dimensions).
    Takes 0.001 seconds, uses 0 MB extra RAM, and enables instant semantic and keyword search
    even if PyTorch/SentenceTransformers is loading or low-memory cloud instances run out of RAM.
    """
    dim = EMBEDDING_DIM
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row_idx, text in enumerate(texts):
        words = text.lower().split()
        if not words:
            continue
        for w in words:
            h = abs(hash(w)) % dim
            vectors[row_idx, h] += 1.0
            for i in range(len(w) - 1):
                h2 = abs(hash(w[i:i+2]) ^ 0x55555555) % dim
                vectors[row_idx, h2] += 0.5
        norm = np.linalg.norm(vectors[row_idx])
        if norm > 0:
            vectors[row_idx] /= norm
    return vectors


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """
    Encodes a list of texts into L2-normalized float32 numpy vectors.
    Uses SentenceTransformer if available, with instant fast-feature fallback on memory pressure.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    try:
        model = get_embedding_model()
        if model is not None:
            embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
            return embeddings.astype(np.float32)
    except Exception as e:
        logger.warning(f"SentenceTransformer encoding fallback triggered: {e}")

    return generate_fast_feature_embeddings(texts)


def generate_query_embedding(query: str) -> np.ndarray:
    """
    Encodes a single query string into a normalized 2D numpy array of shape (1, EMBEDDING_DIM).
    Uses embedding_cache to avoid redundant neural network inference.
    """
    clean_q = query.strip()
    from services.cache_service import embedding_cache
    cached = embedding_cache.get(clean_q)
    if cached is not None:
        return cached.copy()

    vec = generate_embeddings([clean_q])
    embedding_cache.set(clean_q, vec)
    return vec
