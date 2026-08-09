from scripts.rebuild_index_from_redis import rebuild_from_redis


def test_rebuild_from_redis_readds_every_live_cache_entry(isolated_cache):
    import faiss

    import app.cache as cache

    cache.store_cache("What is the capital of France?", "Paris")
    cache.store_cache("Explain gravity", "It pulls things down")

    fresh_index = faiss.IndexFlatIP(cache.dimension)
    store, skipped = rebuild_from_redis(isolated_cache, fresh_index, cache.get_embedding)

    assert skipped == 0
    assert set(store) == {"What is the capital of France?", "Explain gravity"}
    assert fresh_index.ntotal == 2


def test_rebuild_from_redis_skips_status_keys(isolated_cache):
    import faiss

    import app.cache as cache

    cache.store_cache("What is the capital of France?", "Paris")
    isolated_cache.setex("status:some-job-id", 300, '{"status": "processing"}')

    fresh_index = faiss.IndexFlatIP(cache.dimension)
    store, skipped = rebuild_from_redis(isolated_cache, fresh_index, cache.get_embedding)

    assert store == ["What is the capital of France?"]
    assert skipped == 0
    assert fresh_index.ntotal == 1


def test_rebuild_from_redis_skips_keys_with_no_live_value(isolated_cache):
    import faiss

    import app.cache as cache

    cache.store_cache("prompt two", "response two")

    # SCAN can surface a key that expires before the following GET runs
    # (real-Redis race). Model that by having scan_iter report a key that
    # has no backing value.
    class RedisWithExpiringKey:
        def scan_iter(self, match=None):
            return list(isolated_cache._store.keys()) + ["expired prompt"]

        def get(self, key):
            return isolated_cache.get(key)

    fresh_index = faiss.IndexFlatIP(cache.dimension)
    store, skipped = rebuild_from_redis(RedisWithExpiringKey(), fresh_index, cache.get_embedding)

    assert store == ["prompt two"]
    assert skipped == 1
    assert fresh_index.ntotal == 1


def test_rebuild_from_redis_returns_empty_for_empty_redis(isolated_cache):
    import faiss

    import app.cache as cache

    fresh_index = faiss.IndexFlatIP(cache.dimension)
    store, skipped = rebuild_from_redis(isolated_cache, fresh_index, cache.get_embedding)

    assert store == []
    assert skipped == 0
    assert fresh_index.ntotal == 0
