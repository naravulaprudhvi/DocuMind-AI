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

import json
import logging
import os
import threading
import urllib.request
import zlib

import faiss
import numpy as np

logger = logging.getLogger("documind.embedding")

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model_instance = None
_model_lock = threading.Lock()


def get_embedding_model(model_name: str = DEFAULT_MODEL_NAME):
    """Singleton getter for SentenceTransformer with CPU thread limits."""
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
    """Asynchronously pre-loads the SentenceTransformer model in a background thread for local environments."""
    def _warmup():
        try:
            import time
            time.sleep(12)
            get_embedding_model()
        except Exception:
            pass

    t = threading.Thread(target=_warmup, daemon=True, name="embedding-model-warmup")
    t.start()
    return t


def get_embedding_dimension() -> int:
    """Returns the vector dimensionality (384 for all-MiniLM-L6-v2 and Gemini 384-dim)."""
    return EMBEDDING_DIM


def generate_fast_feature_embeddings(texts: list[str]) -> np.ndarray:
    """
    Ultra-lightweight deterministic n-gram & word hashing embedding (384 dimensions).
    Uses C-level zlib.crc32 for cross-process determinism, 0 MB extra RAM, and sub-millisecond execution.
    Completely immune to memory limits and prevents 502 Bad Gateway errors on cloud platforms.
    """
    dim = EMBEDDING_DIM
    vectors = np.zeros((len(texts), dim), dtype=np.float32)
    for row_idx, text in enumerate(texts):
        words = text.lower().split()
        if not words:
            continue
        for w in words:
            # Deterministic word hash via C-level CRC32
            h = zlib.crc32(w.encode("utf-8")) % dim
            vectors[row_idx, h] += 1.0
            # Hash character bigrams for morphological robustness
            for i in range(len(w) - 1):
                h2 = (zlib.crc32(w[i:i+2].encode("utf-8")) ^ 0x55555555) % dim
                vectors[row_idx, h2] += 0.5
        norm = np.linalg.norm(vectors[row_idx])
        if norm > 0:
            vectors[row_idx] /= norm
    return vectors


def generate_gemini_embeddings(texts: list[str], api_key: str) -> np.ndarray | None:
    """
    Generates high-precision 384-dimensional vector embeddings using Google's Gemini Embedding API.
    Zero local RAM and zero CPU load, ideal for cloud environments with 512MB RAM.
    """
    if not texts or not api_key:
        return None

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents?key={api_key}"
        batch_size = 50
        all_vectors = []

        for i in range(0, len(texts), batch_size):
            slice_texts = texts[i:i + batch_size]
            requests = [
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"parts": [{"text": t[:2000]}]},
                    "outputDimensionality": EMBEDDING_DIM,
                }
                for t in slice_texts
            ]
            payload = json.dumps({"requests": requests}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    embeddings = data.get("embeddings", [])
                    for emb in embeddings:
                        vals = emb.get("values", [])
                        if vals and len(vals) == EMBEDDING_DIM:
                            vec = np.array(vals, dtype=np.float32)
                            norm = np.linalg.norm(vec)
                            if norm > 0:
                                vec /= norm
                            all_vectors.append(vec)
                        else:
                            return None
                else:
                    return None

        if len(all_vectors) == len(texts):
            return np.vstack(all_vectors)
    except Exception as e:
        logger.warning(f"Gemini embeddings API error: {e}")

    return None


def generate_embeddings(texts: list[str]) -> np.ndarray:
    """
    Encodes a list of texts into L2-normalized float32 numpy vectors of shape (N, 384).
    1. If GEMINI_API_KEY is available: uses Google's remote embedding API (0 MB RAM, 0% CPU).
    2. If on local machine without cloud constraints: uses SentenceTransformers if present.
    3. Always falls back to deterministic fast-feature embeddings to guarantee zero 502/OOM errors.
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    from config import Config
    is_cloud = getattr(Config, "IS_CLOUD", False)
    gemini_key = os.getenv("GEMINI_API_KEY")

    # 1. High-precision Gemini remote embeddings (preferred on cloud & local if key present)
    if gemini_key:
        gemini_vecs = generate_gemini_embeddings(texts, gemini_key)
        if gemini_vecs is not None and len(gemini_vecs) == len(texts):
            return gemini_vecs

    # 2. Local environment (non-cloud): allow SentenceTransformer if key not configured
    if not is_cloud:
        try:
            model = get_embedding_model()
            if model is not None:
                embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
                return embeddings.astype(np.float32)
        except Exception as e:
            logger.warning(f"SentenceTransformer encoding fallback: {e}")

    # 3. Fast feature fallback (sub-millisecond, 0 MB RAM, prevents 502 OOM on Render)
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
