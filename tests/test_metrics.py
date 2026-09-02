import re


def _metric_value(text: str, name: str, **labels) -> float:
    label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
    pattern = re.compile(rf'^{re.escape(name)}\{{{re.escape(label_str)}\}} ([0-9.eE+-]+)$', re.MULTILINE)
    match = pattern.search(text)
    return float(match.group(1)) if match else 0.0


def test_metrics_endpoint_returns_prometheus_text(api_client):
    response = api_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "semantic_cache_lookup_total" in response.text
    assert "semantic_cache_request_latency_seconds" in response.text


def test_query_on_empty_cache_increments_lookup_counter(api_client):
    before = _metric_value(
        api_client.get("/metrics").text, "semantic_cache_lookup_total", reason="empty_cache"
    )

    response = api_client.post("/query", json={"prompt": "an entirely fresh prompt"})
    assert response.status_code == 202

    after = _metric_value(
        api_client.get("/metrics").text, "semantic_cache_lookup_total", reason="empty_cache"
    )
    assert after == before + 1


def test_cache_hit_increments_hit_counter_and_latency_histogram(api_client):
    api_client.post(
        "/cache/seed", json={"prompt": "What is the capital of France?", "response": "Paris"}
    )

    before_hits = _metric_value(
        api_client.get("/metrics").text, "semantic_cache_lookup_total", reason="hit"
    )
    before_count = _metric_value(
        api_client.get("/metrics").text,
        "semantic_cache_request_latency_seconds_count",
        cache_hit="true",
    )

    response = api_client.post("/query", json={"prompt": "What is the capital of France?"})
    assert response.status_code == 200
    assert response.json()["cached"] is True

    metrics_text = api_client.get("/metrics").text
    after_hits = _metric_value(metrics_text, "semantic_cache_lookup_total", reason="hit")
    after_count = _metric_value(
        metrics_text, "semantic_cache_request_latency_seconds_count", cache_hit="true"
    )

    assert after_hits == before_hits + 1
    assert after_count == before_count + 1
