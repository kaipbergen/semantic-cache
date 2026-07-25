import app.cache as cache
from app.cache import normalize_query


def test_normalize_query_lowercases_and_strips_outer_whitespace():
    assert normalize_query("  Hello World  ") == "hello world"


def test_normalize_query_removes_punctuation():
    assert normalize_query("What's the capital of France?!") == "whats the capital of france"


def test_normalize_query_collapses_internal_whitespace():
    assert normalize_query("hello    world\tfoo\nbar") == "hello world foo bar"


def test_normalize_query_makes_casing_and_punctuation_equivalent():
    assert normalize_query("Hello, World!") == normalize_query("hello world")


def test_normalize_query_empty_string_stays_empty():
    assert normalize_query("") == ""


def test_normalize_query_only_punctuation_becomes_empty():
    assert normalize_query("???!!!") == ""


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
