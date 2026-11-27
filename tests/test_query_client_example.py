import httpx
import pytest

from docs.examples.query_client import SemanticCacheClient


def _client_with_handler(handler, **kwargs):
    client = SemanticCacheClient(**kwargs)
    client._client = httpx.Client(
        base_url=client._client.base_url,
        headers=client._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return client


def test_query_returns_response_on_immediate_hit():
    def handler(request):
        assert request.url.path == "/query"
        return httpx.Response(200, json={"response": "Paris", "cached": True, "status": "done"})

    with _client_with_handler(handler) as client:
        result = client.query("What is the capital of France?")

    assert result == {"response": "Paris", "cached": True, "status": "done"}


def test_query_polls_status_until_done():
    calls = {"status_requests": 0}

    def handler(request):
        if request.url.path == "/query":
            return httpx.Response(202, json={"status": "processing", "job_id": "abc123", "cached": False})
        assert request.url.path == "/status/abc123"
        calls["status_requests"] += 1
        if calls["status_requests"] < 2:
            return httpx.Response(200, json={"status": "processing"})
        return httpx.Response(200, json={"status": "done", "response": "A long answer"})

    with _client_with_handler(handler) as client:
        result = client.query("Explain quantum entanglement", poll_interval=0)

    assert result == {"status": "done", "response": "A long answer"}
    assert calls["status_requests"] == 2


def test_query_poll_timeout_raises():
    def handler(request):
        if request.url.path == "/query":
            return httpx.Response(202, json={"status": "processing", "job_id": "abc123", "cached": False})
        return httpx.Response(200, json={"status": "processing"})

    with _client_with_handler(handler) as client:
        with pytest.raises(TimeoutError):
            client.query("Explain quantum entanglement", poll_interval=0, max_poll_seconds=0)


def test_query_sends_api_key_header_when_configured():
    def handler(request):
        assert request.headers["X-API-Key"] == "secret123"
        return httpx.Response(200, json={"response": "ok", "cached": True, "status": "done"})

    with _client_with_handler(handler, api_key="secret123") as client:
        client.query("hello")


def test_health_returns_json_body():
    def handler(request):
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok", "version": "0.1.0", "uptime_seconds": 12.3})

    with _client_with_handler(handler) as client:
        assert client.health() == {"status": "ok", "version": "0.1.0", "uptime_seconds": 12.3}


def test_query_raises_on_http_error():
    def handler(request):
        return httpx.Response(400, json={"error": {"code": 400, "message": "prompt must not be empty"}})

    with _client_with_handler(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.query("")
