import json

from scripts.export_cache import export_jsonl


def test_export_jsonl_writes_each_prompt_response_pair(isolated_cache, tmp_path):
    import app.cache as cache

    cache.store_cache("What is the capital of France?", "Paris")
    cache.store_cache("Explain gravity", "It pulls things down")

    jsonl_path = tmp_path / "export.jsonl"
    exported, skipped = export_jsonl(str(jsonl_path), cache.prompt_store, isolated_cache, cache._decode_payload)

    assert exported == 2
    assert skipped == 0

    lines = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    assert lines == [
        {"prompt": "What is the capital of France?", "response": "Paris"},
        {"prompt": "Explain gravity", "response": "It pulls things down"},
    ]


def test_export_jsonl_skips_entries_with_expired_redis_key(isolated_cache, tmp_path):
    import app.cache as cache

    cache.store_cache("prompt one", "response one")
    cache.store_cache("prompt two", "response two")
    isolated_cache.delete("prompt one")

    jsonl_path = tmp_path / "export.jsonl"
    exported, skipped = export_jsonl(str(jsonl_path), cache.prompt_store, isolated_cache, cache._decode_payload)

    assert exported == 1
    assert skipped == 1
    lines = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    assert lines == [{"prompt": "prompt two", "response": "response two"}]


def test_export_jsonl_decodes_compressed_payloads(isolated_cache, tmp_path, monkeypatch):
    import app.cache as cache

    monkeypatch.setattr(cache, "COMPRESSION_THRESHOLD_BYTES", 10)
    cache.store_cache("Explain a very long topic", "x" * 500)

    jsonl_path = tmp_path / "export.jsonl"
    exported, skipped = export_jsonl(str(jsonl_path), cache.prompt_store, isolated_cache, cache._decode_payload)

    assert exported == 1
    lines = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    assert lines[0]["response"] == "x" * 500


def test_export_jsonl_returns_zero_for_empty_store(isolated_cache, tmp_path):
    jsonl_path = tmp_path / "export.jsonl"
    exported, skipped = export_jsonl(str(jsonl_path), [], isolated_cache, lambda x: x)

    assert exported == 0
    assert skipped == 0
    assert jsonl_path.read_text() == ""
