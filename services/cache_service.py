from __future__ import annotations

import collections
import hashlib
import time
from typing import Any


class CacheStats:
    def __init__(self):
        self.hits = 0
        self.misses = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.hits / self.total_requests, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": self.total_requests,
            "hit_ratio": self.hit_ratio,
        }


class LRUCache:
    """Thread-safe-ready in-memory LRU cache with TTL support."""

    def __init__(self, capacity: int = 256, default_ttl_seconds: int = 600):
        self.capacity = capacity
        self.default_ttl = default_ttl_seconds
        self._cache: collections.OrderedDict[str, tuple[Any, float]] = collections.OrderedDict()
        self.stats = CacheStats()

    def get(self, key: str) -> Any | None:
        if key not in self._cache:
            self.stats.misses += 1
            return None

        val, expiry = self._cache[key]
        if time.time() > expiry:
            # Expired
            del self._cache[key]
            self.stats.misses += 1
            return None

        self._cache.move_to_end(key)
        self.stats.hits += 1
        return val

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expiry = time.time() + ttl

        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self.capacity:
            # Evict oldest
            self._cache.popitem(last=False)

        self._cache[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        self._cache.clear()

    def size(self) -> int:
        # Purge expired items first
        now = time.time()
        expired_keys = [k for k, (_, exp) in self._cache.items() if now > exp]
        for k in expired_keys:
            del self._cache[k]
        return len(self._cache)


# Global Cache Instances
# 1. Embedding Cache: Caches 384-d normalized float vectors for text queries
embedding_cache = LRUCache(capacity=512, default_ttl_seconds=3600)

# 2. Query/RAG Response Cache: Caches RAG answers and sources for identical query+doc sets
query_response_cache = LRUCache(capacity=256, default_ttl_seconds=600)

# 3. FAISS Index Memory Cache: Caches loaded faiss.IndexIDMap objects by doc_id to avoid repeated disk reads
faiss_index_cache = LRUCache(capacity=64, default_ttl_seconds=1800)

# 4. Document Summary Cache: Caches executive summaries to avoid repeated LLM calls on revisiting document summaries
summary_cache = LRUCache(capacity=64, default_ttl_seconds=3600)


def generate_query_cache_key(user_id: int, query: str, doc_ids: list[int] | None = None) -> str:
    """Generates a consistent hash key for caching RAG query responses."""
    sorted_docs = sorted(doc_ids) if doc_ids else []
    raw = f"{user_id}:{sorted_docs}:{query.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cache_metrics() -> dict[str, Any]:
    """Returns aggregated cache performance telemetry."""
    return {
        "embedding_cache": {
            "size": embedding_cache.size(),
            "capacity": embedding_cache.capacity,
            **embedding_cache.stats.to_dict(),
        },
        "query_cache": {
            "size": query_response_cache.size(),
            "capacity": query_response_cache.capacity,
            **query_response_cache.stats.to_dict(),
        },
        "faiss_index_cache": {
            "size": faiss_index_cache.size(),
            "capacity": faiss_index_cache.capacity,
            **faiss_index_cache.stats.to_dict(),
        },
    }
