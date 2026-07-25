import app.cache as cache


def test_isolated_cache_round_trip(isolated_cache):
    assert cache.index.ntotal == 0
    cache.store_cache("What is the capital of France?", "Paris")
    assert cache.index.ntotal == 1

    result, similarity = cache.search_cache("What is the capital of France?")
    assert result == "Paris"
    assert similarity == 1.0


def test_isolated_cache_state_does_not_leak_between_tests(isolated_cache):
    assert cache.index.ntotal == 0
    assert cache.prompt_store == []
    assert cache.stats["total_requests"] == 0
