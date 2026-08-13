import pytest

from scripts.load_test import run_load_test, summarize


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeClient:
    def __init__(self, status_codes=None, fail_on=None):
        self.status_codes = status_codes or {}
        self.fail_on = fail_on or set()
        self.calls = 0

    async def post(self, url, json, timeout):
        self.calls += 1
        prompt = json["prompt"]
        if prompt in self.fail_on:
            raise ConnectionError("connection reset")
        return _FakeResponse(self.status_codes.get(prompt, 200))


@pytest.mark.asyncio
async def test_run_load_test_returns_one_result_per_prompt():
    client = _FakeClient()
    prompts = [f"prompt {i}" for i in range(5)]

    results = await run_load_test(client, "http://api", prompts, concurrency=2)

    assert len(results) == 5
    assert client.calls == 5
    assert all(r["status_code"] == 200 and r["error"] is None for r in results)


@pytest.mark.asyncio
async def test_run_load_test_respects_concurrency_limit():
    import asyncio

    max_in_flight = 0
    in_flight = 0
    lock = asyncio.Lock()

    class _TrackingClient:
        async def post(self, url, json, timeout):
            nonlocal max_in_flight, in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            async with lock:
                in_flight -= 1
            return _FakeResponse(200)

    prompts = [f"prompt {i}" for i in range(20)]
    await run_load_test(_TrackingClient(), "http://api", prompts, concurrency=3)

    assert max_in_flight <= 3


@pytest.mark.asyncio
async def test_run_load_test_captures_errors_without_raising():
    client = _FakeClient(fail_on={"prompt 1"})
    prompts = ["prompt 0", "prompt 1", "prompt 2"]

    results = await run_load_test(client, "http://api", prompts, concurrency=2)

    failed = [r for r in results if r["error"] is not None]
    assert len(failed) == 1
    assert failed[0]["error"] == "connection reset"
    assert failed[0]["status_code"] is None


def test_summarize_computes_latency_and_error_stats():
    results = [
        {"status_code": 200, "elapsed_ms": 10.0, "error": None},
        {"status_code": 200, "elapsed_ms": 20.0, "error": None},
        {"status_code": 202, "elapsed_ms": 30.0, "error": None},
        {"status_code": 500, "elapsed_ms": 40.0, "error": None},
        {"status_code": None, "elapsed_ms": 5.0, "error": "timeout"},
    ]

    summary = summarize(results)

    assert summary["total_requests"] == 5
    assert summary["errors"] == 2
    assert summary["max_latency_ms"] == 40.0
    assert summary["avg_latency_ms"] == pytest.approx(21.0)


def test_summarize_handles_empty_results():
    summary = summarize([])

    assert summary == {
        "total_requests": 0,
        "errors": 0,
        "avg_latency_ms": 0.0,
        "p50_latency_ms": 0.0,
        "p95_latency_ms": 0.0,
        "p99_latency_ms": 0.0,
        "max_latency_ms": 0.0,
    }
