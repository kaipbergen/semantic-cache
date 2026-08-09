import asyncio

import pytest
from fastapi import HTTPException


def test_query_rejects_empty_prompt(api_client):
    response = api_client.post("/query", json={"prompt": ""})
    assert response.status_code == 400


def test_query_rejects_whitespace_only_prompt(api_client):
    response = api_client.post("/query", json={"prompt": "   \t\n  "})
    assert response.status_code == 400


def test_query_rejects_prompt_over_max_length(api_client):
    import app.main as main_module

    response = api_client.post("/query", json={"prompt": "a" * (main_module.MAX_PROMPT_LENGTH + 1)})
    assert response.status_code == 413


def test_query_allows_prompt_at_max_length(api_client, monkeypatch):
    import app.main as main_module

    # Cache miss on an unresolved Kafka round trip would block for the full
    # RESPONSE_TIMEOUT_SECONDS; shrink it so the test only checks that the
    # length check itself didn't reject the request.
    monkeypatch.setattr(main_module, "RESPONSE_TIMEOUT_SECONDS", 0.05)
    response = api_client.post("/query", json={"prompt": "a" * main_module.MAX_PROMPT_LENGTH})
    assert response.status_code == 202


def test_seed_cache_then_query_is_a_hit(api_client):
    seed_response = api_client.post(
        "/cache/seed", json={"prompt": "What is the capital of France?", "response": "Paris"}
    )
    assert seed_response.status_code == 201

    query_response = api_client.post("/query", json={"prompt": "What is the capital of France?"})
    assert query_response.status_code == 200
    body = query_response.json()
    assert body["cached"] is True
    assert body["response"] == "Paris"
    assert body["similarity"] is not None
    assert body["latency_ms"] is not None

    entries = api_client.get("/cache/entries").json()
    assert entries["total"] == 1
    assert entries["entries"][0]["prompt"] == "What is the capital of France?"


def test_seed_cache_rejects_empty_prompt(api_client):
    response = api_client.post("/cache/seed", json={"prompt": "  ", "response": "Paris"})
    assert response.status_code == 400


def test_list_cache_entries_returns_seeded_prompts_with_ttl(api_client):
    api_client.post("/cache/seed", json={"prompt": "What is the capital of France?", "response": "Paris"})
    api_client.post("/cache/seed", json={"prompt": "Explain gravity", "response": "It pulls things down"})

    response = api_client.get("/cache/entries")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    prompts = {entry["prompt"] for entry in body["entries"]}
    assert prompts == {"What is the capital of France?", "Explain gravity"}
    assert all(entry["ttl_seconds"] > 0 for entry in body["entries"])


def test_list_cache_entries_pagination(api_client):
    for i in range(5):
        api_client.post("/cache/seed", json={"prompt": f"prompt {i}", "response": f"response {i}"})

    response = api_client.get("/cache/entries", params={"limit": 2, "offset": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 3
    assert len(body["entries"]) == 2


def test_list_cache_entries_rejects_invalid_pagination(api_client):
    response = api_client.get("/cache/entries", params={"limit": 0})
    assert response.status_code == 400


def test_rate_limit_blocks_requests_once_bucket_is_exhausted(api_client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "RATE_LIMIT_CAPACITY", 2)
    monkeypatch.setattr(main_module, "RATE_LIMIT_REFILL_PER_SECOND", 0)
    monkeypatch.setattr(main_module, "rate_limit_buckets", {})

    api_client.post("/cache/seed", json={"prompt": "ping", "response": "pong"})

    first = api_client.post("/query", json={"prompt": "ping"})
    second = api_client.post("/query", json={"prompt": "ping"})
    third = api_client.post("/query", json={"prompt": "ping"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


def test_http_exception_uses_structured_error_schema(api_client):
    response = api_client.post("/query", json={"prompt": ""})
    assert response.status_code == 400
    body = response.json()
    assert body == {"error": {"code": 400, "message": "prompt must not be empty"}}


def test_http_exception_404_uses_structured_error_schema(api_client):
    response = api_client.get("/status/nonexistent-job")
    assert response.status_code == 404
    body = response.json()
    assert body == {"error": {"code": 404, "message": "Job not found"}}


def test_response_includes_generated_x_request_id_header(api_client):
    response = api_client.get("/health")
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) > 0


def test_response_echoes_incoming_x_request_id_header(api_client):
    response = api_client.get("/health", headers={"X-Request-ID": "my-custom-id"})
    assert response.headers["X-Request-ID"] == "my-custom-id"


def test_query_rejects_out_of_range_timeout_override(api_client):
    import app.main as main_module

    response = api_client.post(
        "/query",
        json={"prompt": "ping"},
        params={"timeout": main_module.MAX_TIMEOUT_OVERRIDE_SECONDS + 1},
    )
    assert response.status_code == 400


def test_query_rejects_non_positive_timeout_override(api_client):
    response = api_client.post("/query", json={"prompt": "ping"}, params={"timeout": 0})
    assert response.status_code == 400


def test_query_honors_timeout_override_on_cache_miss(api_client):
    import time

    start = time.time()
    response = api_client.post("/query", json={"prompt": "uncached prompt"}, params={"timeout": 0.05})
    elapsed = time.time() - start

    assert response.status_code == 202
    assert elapsed < 1.0


def test_health_deep_reports_healthy_when_all_checks_pass(api_client):
    response = api_client.get("/health/deep")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["redis"] is True
    assert body["checks"]["faiss_index"] is True
    assert body["checks"]["kafka"] is True


def test_health_deep_reports_unhealthy_when_redis_ping_fails(api_client, monkeypatch):
    import app.main as main_module

    def failing_ping():
        raise ConnectionError("redis down")

    monkeypatch.setattr(main_module.redis_client, "ping", failing_ping)

    response = api_client.get("/health/deep")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["redis"] is False


def test_api_key_not_required_when_unset(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200


def test_api_key_rejects_missing_key_when_configured(api_client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "API_KEY", "secret123")
    response = api_client.get("/stats")
    assert response.status_code == 401
    assert response.json() == {"error": {"code": 401, "message": "Invalid or missing API key"}}


def test_api_key_rejects_wrong_key_when_configured(api_client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "API_KEY", "secret123")
    response = api_client.get("/stats", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_api_key_allows_correct_key_when_configured(api_client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "API_KEY", "secret123")
    response = api_client.get("/stats", headers={"X-API-Key": "secret123"})
    assert response.status_code == 200


def test_api_key_exempts_health_endpoint_even_when_configured(api_client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "API_KEY", "secret123")
    response = api_client.get("/health")
    assert response.status_code == 200


def test_cors_preflight_request_is_allowed(api_client):
    response = api_client.options(
        "/query",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors_headers_present_on_actual_response(api_client):
    response = api_client.get("/health", headers={"Origin": "https://example.com"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors_allowed_origins_env_var_is_parsed_into_a_list(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://a.com, https://b.com")
    import importlib

    import app.main as main_module

    importlib.reload(main_module)
    try:
        assert main_module.CORS_ALLOWED_ORIGINS == ["https://a.com", "https://b.com"]
    finally:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        importlib.reload(main_module)


def test_bypass_cache_skips_hit_and_falls_through_to_llm_path(api_client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "RESPONSE_TIMEOUT_SECONDS", 0.05)
    api_client.post(
        "/cache/seed", json={"prompt": "What is the capital of France?", "response": "Paris"}
    )

    response = api_client.post(
        "/query", json={"prompt": "What is the capital of France?"}, params={"bypass_cache": "true"}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["cached"] is False


def test_bypass_cache_false_still_returns_cache_hit(api_client):
    api_client.post(
        "/cache/seed", json={"prompt": "What is the capital of France?", "response": "Paris"}
    )

    response = api_client.post(
        "/query", json={"prompt": "What is the capital of France?"}, params={"bypass_cache": "false"}
    )
    assert response.status_code == 200
    assert response.json()["cached"] is True


def test_clear_cache_resets_index_and_redis_together(api_client, monkeypatch):
    import app.main as main_module

    api_client.post("/cache/seed", json={"prompt": "What is the capital of France?", "response": "Paris"})
    api_client.post("/cache/seed", json={"prompt": "Explain gravity", "response": "It pulls things down"})

    entries_before = api_client.get("/cache/entries").json()
    assert entries_before["total"] == 2

    response = api_client.delete("/cache")
    assert response.status_code == 200
    assert response.json() == {"message": "Cache cleared", "deleted": "all"}

    entries_after = api_client.get("/cache/entries").json()
    assert entries_after["total"] == 0

    stats_after = api_client.get("/stats").json()
    assert stats_after["total_cached_prompts"] == 0

    monkeypatch.setattr(main_module, "RESPONSE_TIMEOUT_SECONDS", 0.05)
    query_response = api_client.post("/query", json={"prompt": "What is the capital of France?"})
    assert query_response.status_code == 202
    assert query_response.json()["cached"] is False


def test_query_batch_returns_hit_and_miss_results(api_client):
    api_client.post(
        "/cache/seed", json={"prompt": "What is the capital of France?", "response": "Paris"}
    )

    response = api_client.post(
        "/query/batch",
        json={"prompts": ["What is the capital of France?", "completely unrelated text xyz"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["prompt"] == "What is the capital of France?"
    assert body[0]["cached"] is True
    assert body[0]["response"] == "Paris"
    assert body[1]["prompt"] == "completely unrelated text xyz"
    assert body[1]["cached"] is False
    assert body[1]["response"] is None


def test_query_batch_rejects_empty_prompt_list(api_client):
    response = api_client.post("/query/batch", json={"prompts": []})
    assert response.status_code == 400


def test_query_batch_rejects_blank_prompt_in_list(api_client):
    response = api_client.post("/query/batch", json={"prompts": ["valid", "   "]})
    assert response.status_code == 400


def test_query_batch_rejects_over_max_batch_size(api_client, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "MAX_BATCH_SIZE", 2)
    response = api_client.post("/query/batch", json={"prompts": ["a", "b", "c"]})
    assert response.status_code == 413


def test_rate_limit_is_tracked_per_client_ip(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "RATE_LIMIT_CAPACITY", 1)
    monkeypatch.setattr(main_module, "RATE_LIMIT_REFILL_PER_SECOND", 0)
    monkeypatch.setattr(main_module, "rate_limit_buckets", {})

    main_module.check_rate_limit("1.1.1.1")
    with pytest.raises(HTTPException):
        main_module.check_rate_limit("1.1.1.1")

    # A different client IP has its own bucket and is unaffected.
    main_module.check_rate_limit("2.2.2.2")


def test_prune_once_removes_expired_entries(isolated_cache):
    import app.cache as cache
    import app.main as main_module

    cache.store_cache("prompt one", "response one")
    cache.store_cache("prompt two", "response two")
    isolated_cache.delete("prompt one")

    removed = main_module._prune_once()

    assert removed == 1
    assert cache.prompt_store == ["prompt two"]


def test_prune_once_returns_zero_when_nothing_expired(isolated_cache):
    import app.cache as cache
    import app.main as main_module

    cache.store_cache("prompt one", "response one")

    removed = main_module._prune_once()

    assert removed == 0
    assert cache.prompt_store == ["prompt one"]


@pytest.mark.asyncio
async def test_prune_expired_entries_loop_prunes_on_each_tick(isolated_cache, monkeypatch):
    import app.cache as cache
    import app.main as main_module

    cache.store_cache("prompt one", "response one")
    isolated_cache.delete("prompt one")

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(main_module, "COMPACTION_INTERVAL_SECONDS", 30)
    monkeypatch.setattr(main_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await main_module.prune_expired_entries()

    assert sleep_calls == [30, 30]
    assert cache.prompt_store == []
