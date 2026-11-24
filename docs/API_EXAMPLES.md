# API Usage Examples

Runnable examples for every endpoint, as `curl` and as Python (using
[`httpx`](https://www.python-httpx.org/), already a transitive dependency via
FastAPI's test client - `pip install httpx` if you don't have it otherwise).

All examples assume the API is running locally per the [Quick Start](../README.md#-quick-start)
and reachable at `http://localhost:8000`. If `API_KEY` is set in your environment, add an
`X-API-Key: <value>` header to every request below except `/health`, `/health/deep`, `/docs`,
`/openapi.json`, `/redoc`, and `/metrics` (see `API_KEY_EXEMPT_PATHS` in `app/main.py`).

```python
import httpx

client = httpx.Client(base_url="http://localhost:8000")
```

## POST /query

Semantic cache lookup; on a miss, the request is handed off to the LLM via Kafka and awaited
up to `RESPONSE_TIMEOUT_SECONDS` before falling back to a `202` with a `job_id` to poll.

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is machine learning?"}'
```

```python
response = client.post("/query", json={"prompt": "What is machine learning?"})
print(response.json())
# {"response": "...", "cached": false, "similarity": null, "latency_ms": 842.1,
#  "status": "done", "job_id": null, "cache_reason": "no_candidates"}
```

Optional query params: `?timeout=<seconds>` overrides the default wait before falling back to
`202` (bounded by `MAX_TIMEOUT_OVERRIDE_SECONDS`), `?bypass_cache=true` skips the cache lookup
entirely and always calls the LLM.

```bash
curl -X POST "http://localhost:8000/query?timeout=20&bypass_cache=true" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain quantum entanglement"}'
```

A `202` response means the LLM call is still running - poll `/status/{job_id}` with the
returned `job_id` (useful across API replicas, since the in-process `await` only works on the
replica that received the original request).

## POST /query/batch

Looks up multiple prompts in one call. Each result reports independently whether it was a
cache hit; misses are **not** dispatched to the LLM (`/query` does that per-prompt instead).

```bash
curl -X POST http://localhost:8000/query/batch \
  -H "Content-Type: application/json" \
  -d '{"prompts": ["What is machine learning?", "Explain neural networks"]}'
```

```python
response = client.post(
    "/query/batch",
    json={"prompts": ["What is machine learning?", "Explain neural networks"]},
)
for result in response.json():
    print(result["prompt"], "->", "hit" if result["cached"] else result["cache_reason"])
```

## POST /cache/seed

Manually inserts a prompt/response pair into the cache without going through Kafka - useful for
pre-warming common queries.

```bash
curl -X POST http://localhost:8000/cache/seed \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is the capital of France?", "response": "Paris"}'
```

```python
response = client.post(
    "/cache/seed",
    json={"prompt": "What is the capital of France?", "response": "Paris"},
)
assert response.status_code == 201
```

## GET /cache/entries

Lists cached prompts with pagination and each entry's remaining Redis TTL.

```bash
curl "http://localhost:8000/cache/entries?limit=10&offset=0"
```

```python
response = client.get("/cache/entries", params={"limit": 10, "offset": 0})
print(response.json())
```

## GET /cache/entries/{prompt_hash}

Fetches a single entry's full record (the "prompt_hash" path segment is the literal prompt
string used as the Redis key, matching how `/cache/entries` reports it).

```bash
curl "http://localhost:8000/cache/entries/What%20is%20the%20capital%20of%20France%3F"
```

```python
import urllib.parse

prompt = "What is the capital of France?"
response = client.get(f"/cache/entries/{urllib.parse.quote(prompt, safe='')}")
print(response.json())
```

## GET /status/{job_id}

Polls the status of a `/query` call that returned `202`. Works across API replicas since it
reads from Redis rather than in-process state.

```bash
curl http://localhost:8000/status/3f2504e0-4f89-11d3-9a0c-0305e82c3301
```

```python
response = client.get(f"/status/{job_id}")
print(response.json())  # {"status": "processing"} or {"status": "done", "response": "..."}
```

## GET /stats

Hit rate, latency breakdown, cost savings estimate, and a per-category (factual/definition/
explanation) breakdown.

```bash
curl http://localhost:8000/stats
```

```python
print(client.get("/stats").json())
```

## GET /metrics

Prometheus exposition format - point a Prometheus scrape config at this endpoint rather than
parsing it by hand.

```bash
curl http://localhost:8000/metrics
```

## GET /health and GET /health/deep

`/health` is a cheap liveness check (no dependency calls). `/health/deep` actually pings Redis,
checks the FAISS index is loaded, and checks Kafka broker reachability - use it for readiness
probes, not every load balancer health check, since it's more expensive per call.

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/deep
```

## DELETE /cache

Clears the entire cache (FAISS index and Redis) - irreversible.

```bash
curl -X DELETE http://localhost:8000/cache
```

## DELETE /cache/{prompt_hash}

Deletes a single cache entry by its prompt key.

```bash
curl -X DELETE "http://localhost:8000/cache/What%20is%20the%20capital%20of%20France%3F"
```
