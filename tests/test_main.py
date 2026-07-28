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
