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
