import app.cache as cache
from app.cache import get_adaptive_threshold, normalize_query


def test_get_adaptive_threshold_factual_question():
    assert get_adaptive_threshold("Who invented the telephone?") == 0.90


def test_get_adaptive_threshold_definition_question():
    assert get_adaptive_threshold("Define entropy") == 0.82


def test_get_adaptive_threshold_explanation_question():
    assert get_adaptive_threshold("Explain how neural networks work") == 0.76


def test_get_adaptive_threshold_how_does_is_explanation():
    assert get_adaptive_threshold("How does photosynthesis work?") == 0.76


def test_get_adaptive_threshold_unmatched_prompt_gets_default():
    assert get_adaptive_threshold("Random unrelated statement") == 0.82


def test_get_adaptive_threshold_factual_pattern_takes_precedence():
    # contains both "capital" (factual) and "what is" (definition) - factual wins
    assert get_adaptive_threshold("What is the capital of Kazakhstan?") == 0.90


def test_get_adaptive_threshold_is_case_insensitive():
    assert get_adaptive_threshold("WHO INVENTED the telephone?") == 0.90


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
