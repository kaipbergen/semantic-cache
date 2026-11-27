"""Minimal Python client wrapping POST /query.

Handles the X-API-Key header (if configured) and the 202/job_id polling
fallback for requests that outlast RESPONSE_TIMEOUT_SECONDS, so callers get
a single synchronous call instead of juggling both response shapes
themselves. See docs/API_EXAMPLES.md for curl + Python snippets covering
every other endpoint.

Usage as a script:
    python docs/examples/query_client.py "What is machine learning?"

Usage as a library:
    from docs.examples.query_client import SemanticCacheClient

    with SemanticCacheClient("http://localhost:8000") as client:
        result = client.query("What is machine learning?")
        print(result["response"])
"""

import argparse
import os
import time

import httpx


class SemanticCacheClient:
    def __init__(self, base_url: str = "http://localhost:8000", api_key: str | None = None, timeout: float = 30.0):
        headers = {"X-API-Key": api_key} if api_key else {}
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)

    def query(
        self,
        prompt: str,
        *,
        timeout: float | None = None,
        bypass_cache: bool = False,
        poll_interval: float = 1.0,
        max_poll_seconds: float = 30.0,
    ) -> dict:
        """POST /query, transparently polling /status/{job_id} if the server
        returns 202 before the LLM call finished. Raises httpx.HTTPStatusError
        on a non-2xx response and TimeoutError if polling exceeds
        max_poll_seconds."""
        params = {}
        if timeout is not None:
            params["timeout"] = timeout
        if bypass_cache:
            params["bypass_cache"] = "true"

        response = self._client.post("/query", params=params, json={"prompt": prompt})
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "processing":
            data = self._poll_job(data["job_id"], poll_interval, max_poll_seconds)
        return data

    def _poll_job(self, job_id: str, poll_interval: float, max_poll_seconds: float) -> dict:
        deadline = time.monotonic() + max_poll_seconds
        while True:
            response = self._client.get(f"/status/{job_id}")
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "processing":
                return data
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job {job_id} did not complete within {max_poll_seconds}s")
            time.sleep(poll_interval)

    def health(self) -> dict:
        response = self._client.get("/health")
        response.raise_for_status()
        return response.json()

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def main():
    parser = argparse.ArgumentParser(description="Query the semantic cache API from the command line.")
    parser.add_argument("prompt")
    parser.add_argument("--base-url", default=os.getenv("SEMANTIC_CACHE_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY"))
    parser.add_argument("--bypass-cache", action="store_true")
    args = parser.parse_args()

    with SemanticCacheClient(args.base_url, api_key=args.api_key) as client:
        result = client.query(args.prompt, bypass_cache=args.bypass_cache)
    print(result.get("response", result))


if __name__ == "__main__":
    main()
