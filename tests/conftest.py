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
        self._ttl = {}

    def get(self, key):
        return self._store.get(key)

    def setex(self, key, ttl, value):
        self._store[key] = value
        self._ttl[key] = ttl

    def ttl(self, key):
        return self._ttl.get(key, -2)

    def expire(self, key, ttl):
        if key in self._store:
            self._ttl[key] = ttl
            return True
        return False

    def delete(self, key):
        self._ttl.pop(key, None)
        return 1 if self._store.pop(key, None) is not None else 0

    def flushdb(self):
        self._store.clear()
        self._ttl.clear()

    def ping(self):
        return True


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


class FakeKafkaClient:
    def get_random_node(self):
        return 0

    async def ready(self, node_id, *, group=0):
        return True


class FakeProducer:
    def __init__(self, *args, **kwargs):
        self.sent = []
        self.client = FakeKafkaClient()

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send_and_wait(self, topic, value):
        self.sent.append((topic, value))


@pytest.fixture
def api_client(isolated_cache, monkeypatch):
    # The API's lifespan connects to real Kafka on startup and runs a
    # background consumer task. Tests only exercise HTTP-level behavior, so
    # both are faked out - no Kafka broker needed to test the endpoints.
    from fastapi.testclient import TestClient

    import app.main as main_module

    async def fake_start_with_retry(client, name, retries=15, delay=3.0):
        await client.start()

    async def fake_consume_responses():
        pass

    monkeypatch.setattr(main_module, "AIOKafkaProducer", FakeProducer)
    monkeypatch.setattr(main_module, "start_with_retry", fake_start_with_retry)
    monkeypatch.setattr(main_module, "consume_responses", fake_consume_responses)
    monkeypatch.setattr(main_module, "redis_client", isolated_cache)

    with TestClient(main_module.app) as client:
        yield client
