import hashlib
import os
import sys
import tempfile
import types

import numpy as np
import pytest

os.environ.setdefault("INDEX_DIR", tempfile.mkdtemp(prefix="semantic-cache-test-"))

# app.cache loads real SentenceTransformer/CrossEncoder models at import time,
# which needs network access and ~10s+ per test run. Tests only need
# deterministic vectors, so the heavy ML deps are faked before anything
# imports app.cache.
_EMBED_DIM = 768


class _FakeSentenceTransformer:
    def __init__(self, *args, **kwargs):
        pass

    def encode(self, texts, normalize_embeddings=True):
        vecs = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            raw = np.frombuffer((digest * (_EMBED_DIM // len(digest) + 1))[:_EMBED_DIM], dtype=np.uint8)
            vec = raw.astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vecs.append(vec)
        return np.array(vecs, dtype=np.float32)


class _FakeCrossEncoder:
    def __init__(self, *args, **kwargs):
        pass

    def predict(self, pairs):
        return np.array([1.0 for _ in pairs], dtype=np.float32)


sys.modules["sentence_transformers"] = types.SimpleNamespace(
    SentenceTransformer=_FakeSentenceTransformer,
    CrossEncoder=_FakeCrossEncoder,
)


class FakeRedis:
    def __init__(self):
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def setex(self, key, ttl, value):
        self._store[key] = value

    def delete(self, key):
        return 1 if self._store.pop(key, None) is not None else 0

    def flushdb(self):
        self._store.clear()


@pytest.fixture
def isolated_cache(monkeypatch):
    import faiss

    import app.cache as cache_module

    fake_redis = FakeRedis()
    monkeypatch.setattr(cache_module, "redis_client", fake_redis)
    monkeypatch.setattr(cache_module, "index", faiss.IndexFlatIP(cache_module.dimension))
    monkeypatch.setattr(cache_module, "prompt_store", [])
    monkeypatch.setattr(cache_module, "_save_index", lambda idx, store: None)
    monkeypatch.setattr(
        cache_module,
        "stats",
        {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_cached_latency_ms": 0.0,
            "total_llm_latency_ms": 0.0,
        },
    )
    return fake_redis
