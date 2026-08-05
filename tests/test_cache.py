import os

import faiss

import app.cache as cache
from app.cache import CACHE_TTL_LONG, CACHE_TTL_SHORT, get_adaptive_threshold, get_ttl, normalize_query


def test_get_ttl_explain_keyword_gets_long_ttl():
    assert get_ttl("Explain quantum computing") == CACHE_TTL_LONG


def test_get_ttl_tell_me_about_keyword_gets_long_ttl():
    assert get_ttl("Tell me about black holes") == CACHE_TTL_LONG


def test_get_ttl_how_does_keyword_gets_long_ttl():
    assert get_ttl("How does a car engine work?") == CACHE_TTL_LONG


def test_get_ttl_prompt_without_keyword_gets_short_ttl():
    assert get_ttl("Who invented the telephone?") == CACHE_TTL_SHORT


def test_get_ttl_keyword_match_is_case_insensitive():
    assert get_ttl("EXPLAIN how gravity works") == CACHE_TTL_LONG


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


def test_normalize_query_strips_emoji_without_gluing_adjacent_words():
    assert normalize_query("hello👍world") == "hello world"


def test_normalize_query_strips_emoji_surrounded_by_spaces():
    assert normalize_query("I love pizza 🍕🍕🍕 so much!!!") == "i love pizza so much"


def test_normalize_query_strips_zwj_skin_tone_emoji_sequences():
    assert normalize_query("family 👨‍👩‍👧‍👦 emoji") == "family emoji"


def test_normalize_query_strips_non_ascii_punctuation():
    assert normalize_query("curly “quotes” and «guillemets»") == "curly quotes and guillemets"


def test_normalize_query_keeps_non_ascii_letters():
    assert normalize_query("café naïve") == "café naïve"


def test_isolated_cache_round_trip(isolated_cache):
    assert cache.index.ntotal == 0
    cache.store_cache("What is the capital of France?", "Paris")
    assert cache.index.ntotal == 1

    result, similarity = cache.search_cache("What is the capital of France?")
    assert result == "Paris"
    assert similarity == 1.0


def test_store_cache_does_not_duplicate_existing_prompt_in_index(isolated_cache):
    cache.store_cache("What is the capital of France?", "Paris")
    cache.store_cache("What is the capital of France?", "Paris, France")
    assert cache.index.ntotal == 1
    assert cache.prompt_store == ["What is the capital of France?"]

    result, _ = cache.search_cache("What is the capital of France?")
    assert result == "Paris, France"


def test_search_cache_hit_refreshes_ttl(isolated_cache):
    cache.store_cache("Who invented the telephone?", "Alexander Graham Bell")
    isolated_cache._ttl["Who invented the telephone?"] = 1

    cache.search_cache("Who invented the telephone?")

    assert isolated_cache.ttl("Who invented the telephone?") == CACHE_TTL_SHORT


def test_save_index_writes_via_temp_file_and_rename(tmp_path, monkeypatch):
    index_path = str(tmp_path / "index.faiss")
    store_path = str(tmp_path / "prompt_store.pkl")
    monkeypatch.setattr(cache, "INDEX_PATH", index_path)
    monkeypatch.setattr(cache, "STORE_PATH", store_path)

    idx = faiss.IndexFlatIP(cache.dimension)
    cache._save_index(idx, ["hello"])

    assert os.path.exists(index_path)
    assert os.path.exists(store_path)
    assert not os.path.exists(index_path + ".tmp")
    assert not os.path.exists(store_path + ".tmp")

    loaded_idx = faiss.read_index(index_path)
    assert loaded_idx.ntotal == 0


def test_get_stats_reports_index_size_and_dimension(isolated_cache):
    cache.store_cache("What is the capital of France?", "Paris")
    cache.store_cache("Who invented the telephone?", "Alexander Graham Bell")

    stats = cache.get_stats()

    assert stats["index_dimension"] == cache.dimension
    assert stats["total_cached_prompts"] == 2
    assert stats["index_vectors_bytes"] == 2 * cache.dimension * 4


def test_get_stats_reports_zero_index_bytes_when_empty(isolated_cache):
    stats = cache.get_stats()
    assert stats["index_vectors_bytes"] == 0


def test_isolated_cache_state_does_not_leak_between_tests(isolated_cache):
    assert cache.index.ntotal == 0
    assert cache.prompt_store == []
    assert cache.stats["total_requests"] == 0


def test_bi_encoder_model_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("BI_ENCODER_MODEL", "some-other-model")
    import importlib

    importlib.reload(cache)
    try:
        assert cache.BI_ENCODER_MODEL == "some-other-model"
    finally:
        monkeypatch.delenv("BI_ENCODER_MODEL", raising=False)
        importlib.reload(cache)


def test_store_cache_evicts_oldest_entry_when_over_max_cache_size(isolated_cache, monkeypatch):
    monkeypatch.setattr(cache, "MAX_CACHE_SIZE", 2)

    cache.store_cache("prompt one", "response one")
    cache.store_cache("prompt two", "response two")
    cache.store_cache("prompt three", "response three")

    assert cache.index.ntotal == 2
    assert cache.prompt_store == ["prompt two", "prompt three"]
    assert isolated_cache.get("prompt one") is None

    result, _ = cache.search_cache("prompt one")
    assert result is None

    result, _ = cache.search_cache("prompt three")
    assert result == "response three"


def test_store_cache_evicts_multiple_entries_when_far_over_max_cache_size(isolated_cache, monkeypatch):
    monkeypatch.setattr(cache, "MAX_CACHE_SIZE", 1)

    cache.store_cache("prompt one", "response one")
    cache.store_cache("prompt two", "response two")

    assert cache.index.ntotal == 1
    assert cache.prompt_store == ["prompt two"]


def test_store_cache_does_not_evict_when_max_cache_size_unset(isolated_cache):
    assert cache.MAX_CACHE_SIZE == 0
    for i in range(10):
        cache.store_cache(f"prompt {i}", f"response {i}")
    assert cache.index.ntotal == 10


def test_cross_encoder_model_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("CROSS_ENCODER_MODEL", "some-other-reranker")
    import importlib

    importlib.reload(cache)
    try:
        assert cache.CROSS_ENCODER_MODEL == "some-other-reranker"
    finally:
        monkeypatch.delenv("CROSS_ENCODER_MODEL", raising=False)
        importlib.reload(cache)
