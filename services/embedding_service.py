import os

import numpy as np

# Suppress TensorFlow / oneDNN and Windows symlink warnings
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import threading
import faiss

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model_instance = None
_model_lock = threading.Lock()


def get_embedding_model(model_name: str = DEFAULT_MODEL_NAME):
    """Singleton getter for the SentenceTransformer model."""
    global _model_instance
    if _model_instance is None:
        with _model_lock:
            if _model_instance is None:
                from sentence_transformers import SentenceTransformer

                _model_instance = SentenceTransformer(model_name)
    return _model_instance


def warmup_embedding_model_async():
    """Asynchronously pre-loads the SentenceTransformer model in a background thread."""
    def _warmup():
        try:
            import time
            time.sleep(8)  # Allow web server to boot and respond to initial health checks and page requests
            get_embedding_model()
        except Exception:
            pass

    t = threading.Thread(target=_warmup, daemon=True, name="embedding-model-warmup")
    t.start()
    return t


def get_embedding_dimension() -> int:
    """Returns the vector dimensionality (384 for all-MiniLM-L6-v2)."""
    return EMBEDDING_DIM


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """
    Encodes a list of texts into L2-normalized float32 numpy vectors.
    L2-normalized vectors allow using Inner Product for exact Cosine Similarity.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    model = get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
    embeddings = embeddings.astype(np.float32)
    return embeddings


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
