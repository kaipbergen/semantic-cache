import json

from scripts.warmup_cache import load_jsonl


def test_load_jsonl_stores_each_prompt_response_pair(isolated_cache, tmp_path):
    import app.cache as cache

    jsonl_path = tmp_path / "seed.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"prompt": "What is the capital of France?", "response": "Paris"}),
                json.dumps({"prompt": "Explain gravity", "response": "It pulls things down"}),
            ]
        )
    )

    loaded, skipped = load_jsonl(str(jsonl_path), cache.store_cache)

    assert loaded == 2
    assert skipped == 0
    assert cache.index.ntotal == 2
    result, _ = cache.search_cache("What is the capital of France?")
    assert result == "Paris"


def test_load_jsonl_skips_malformed_and_empty_lines(isolated_cache, tmp_path):
    import app.cache as cache

    jsonl_path = tmp_path / "seed.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"prompt": "valid prompt", "response": "valid response"}),
                "not valid json",
                json.dumps({"prompt": "   ", "response": "blank prompt"}),
                json.dumps({"response": "missing prompt key"}),
                "",
            ]
        )
    )

    loaded, skipped = load_jsonl(str(jsonl_path), cache.store_cache)

    assert loaded == 1
    assert skipped == 3
    assert cache.index.ntotal == 1


def test_load_jsonl_returns_zero_for_empty_file(isolated_cache, tmp_path):
    import app.cache as cache

    jsonl_path = tmp_path / "empty.jsonl"
    jsonl_path.write_text("")

    loaded, skipped = load_jsonl(str(jsonl_path), cache.store_cache)

    assert loaded == 0
    assert skipped == 0
    assert cache.index.ntotal == 0
