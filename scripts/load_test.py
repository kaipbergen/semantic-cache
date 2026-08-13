import argparse
import asyncio
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _fire_one(client, url, prompt, timeout):
    start = time.time()
    try:
        response = await client.post(url, json={"prompt": prompt}, timeout=timeout)
        return {
            "status_code": response.status_code,
            "elapsed_ms": (time.time() - start) * 1000,
            "error": None,
        }
    except Exception as exc:
        return {
            "status_code": None,
            "elapsed_ms": (time.time() - start) * 1000,
            "error": str(exc),
        }


async def run_load_test(client, base_url: str, prompts: list[str], concurrency: int, timeout: float = 10.0):
    """Fire `prompts` at POST {base_url}/query, at most `concurrency` in flight
    at once. Returns one result dict per prompt."""
    url = f"{base_url}/query"
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(prompt):
        async with semaphore:
            return await _fire_one(client, url, prompt, timeout)

    return await asyncio.gather(*(_bounded(p) for p in prompts))


def summarize(results: list[dict]) -> dict:
    """Aggregate raw per-request results into latency/error summary stats."""
    latencies = sorted(r["elapsed_ms"] for r in results)
    errors = [r for r in results if r["error"] is not None or r["status_code"] not in (200, 202)]

    def _percentile(p: float) -> float:
        if not latencies:
            return 0.0
        idx = min(len(latencies) - 1, int(len(latencies) * p))
        return latencies[idx]

    return {
        "total_requests": len(results),
        "errors": len(errors),
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p50_latency_ms": round(_percentile(0.50), 2),
        "p95_latency_ms": round(_percentile(0.95), 2),
        "p99_latency_ms": round(_percentile(0.99), 2),
        "max_latency_ms": round(latencies[-1], 2) if latencies else 0.0,
    }


async def _main_async(args):
    import httpx

    prompts = [f"{args.prompt} {i}" for i in range(args.requests)]
    async with httpx.AsyncClient() as client:
        results = await run_load_test(client, args.base_url, prompts, args.concurrency, args.timeout)

    summary = summarize(results)
    print(f"requests={summary['total_requests']} errors={summary['errors']}")
    print(
        "latency_ms avg={avg_latency_ms} p50={p50_latency_ms} p95={p95_latency_ms} "
        "p99={p99_latency_ms} max={max_latency_ms}".format(**summary)
    )


def main():
    parser = argparse.ArgumentParser(description="Concurrent load test against POST /query")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--requests", type=int, default=100, help="Total number of requests to send")
    parser.add_argument("--concurrency", type=int, default=10, help="Max requests in flight at once")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    parser.add_argument("--prompt", default="load test prompt", help="Base prompt text (suffixed with an index)")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
