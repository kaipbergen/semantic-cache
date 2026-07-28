# Semantic Cache — 100 Days of Code

A 100-day roadmap of real, scoped improvements to the LLM semantic cache, executed in
batches by an automated daily task (this project runs on alternating days, 5 items per run).
Each run: implement the items, verify (tests / smoke test), commit, push. No filler commits —
if an item can't be completed and verified, it stays unchecked and gets picked up next run.

Progress is tracked by checking items off below (`- [ ]` → `- [x] (Day N, YYYY-MM-DD)`).

## API & endpoints
- [x] Input validation: reject empty/whitespace-only prompts with 400 (Day 2, 2026-07-28)
- [ ] Input validation: enforce max prompt length via env var, 413 on overflow
- [ ] POST /cache/seed to manually insert a prompt→response pair without going through Kafka
- [ ] GET /cache/entries with pagination to list cached prompts and their TTLs
- [ ] Rate limiting per client IP (token bucket) on /query
- [ ] Request correlation ID returned in an X-Request-ID response header
- [ ] Configurable per-request timeout override via query param on /query
- [ ] /health deep check: verify Redis ping, FAISS index loaded, Kafka broker reachable
- [ ] Optional API key auth middleware, enabled via env var
- [ ] Consistent structured JSON error schema for all HTTPException responses
- [ ] OPTIONS/CORS preflight support for browser-based clients
- [ ] Query parameter to bypass cache lookup and force a fresh LLM call (?bypass_cache=true)

## Cache core
- [ ] Sliding TTL: refresh a cache entry's expiration on hit
- [ ] Configurable max cache size with LRU eviction of oldest FAISS/prompt_store entries
- [ ] POST /query/batch for looking up multiple prompts in one call
- [ ] Prompt normalization: strip emoji/non-ASCII punctuation consistently
- [ ] Duplicate-prompt guard in store_cache to avoid re-adding an existing prompt to the index
- [ ] Per-namespace cache isolation via an optional namespace field on requests
- [ ] Configurable bi-encoder model name via env var
- [ ] Cache warmup script: preload FAISS index + Redis from a JSONL file of prompt/response pairs
- [ ] Adaptive threshold auto-tuning based on observed hit/miss outcomes
- [ ] Cache entry versioning to support safely swapping embedding models without stale vectors
- [ ] Response compression for large cached payloads stored in Redis
- [ ] Configurable cross-encoder model name via env var

## Index management
- [ ] Atomic FAISS index persistence: write to temp file + rename instead of in-place overwrite
- [ ] Index compaction command: rebuild the index dropping entries whose Redis TTL has expired
- [ ] Backup/restore CLI script for the FAISS index + prompt_store
- [ ] Background task to periodically prune expired entries from prompt_store
- [ ] Migration path from IndexFlatIP to IndexIVFFlat for larger-scale recall/perf tradeoff
- [ ] Index integrity check on startup (detect prompt_store/index size mismatch)
- [x] Configurable index storage path via env var (currently hardcoded /app path) (Day 1, 2026-07-25)
- [ ] Export cache contents to JSONL for inspection/debugging
- [ ] CLI script to rebuild the FAISS index from Redis contents alone (disaster recovery)
- [ ] Metrics on index size/memory footprint exposed via /stats

## Testing
- [x] pytest fixtures providing isolated Redis + FAISS state per test (Day 1, 2026-07-25)
- [x] Unit tests for normalize_query edge cases (punctuation, whitespace, casing) (Day 1, 2026-07-25)
- [x] Unit tests for get_adaptive_threshold pattern matching across categories (Day 1, 2026-07-25)
- [x] Unit tests for get_ttl keyword classification (Day 1, 2026-07-25)
- [ ] Integration test: seed cache then assert /query returns a cache hit
- [ ] Integration test: cache miss path with a mocked Kafka producer/consumer
- [ ] Integration test: /status/{job_id} polling fallback on timeout
- [ ] Test coverage reporting via pytest-cov
- [ ] Regression test for clear_cache endpoint resetting index + Redis together
- [ ] Load test script (locust or asyncio-based) exercising /query concurrently
- [ ] Contract test verifying PromptResponse schema stability
- [ ] CI job matrix testing against two Python versions

## Kafka / async pipeline
- [ ] Dead-letter topic for LLM requests that fail after N retries
- [ ] Kafka producer retry with exponential backoff on send_and_wait failures
- [ ] Idempotent response handling: dedupe on correlation_id if a message is redelivered
- [ ] Graceful consumer shutdown draining in-flight messages before exit
- [ ] Kafka consumer lag exposed via /stats
- [ ] Configurable consumer group ID via env var for horizontal scaling
- [ ] Poison-message handling: skip and log malformed Kafka payloads instead of crashing the consumer
- [ ] Startup readiness check that blocks serving traffic until Kafka topics exist
- [ ] Kafka topic auto-creation with sane partition/replication defaults documented
- [ ] Backpressure handling: bound pending_requests size and reject new requests when saturated

## Observability
- [ ] Prometheus /metrics endpoint (request count, hit rate, latency histograms)
- [ ] Structured JSON logging with request correlation IDs
- [ ] /stats breakdown by adaptive-threshold category (factual/definition/explanation)
- [ ] Slow-query logging for LLM calls exceeding a configurable latency threshold
- [ ] Grafana dashboard JSON for the Prometheus metrics
- [ ] Request/response logging middleware with configurable verbosity
- [ ] /stats historical rollup (hourly buckets) instead of only cumulative counters
- [ ] Sentry or similar error-tracking integration hook (optional, env-gated)
- [ ] Cache hit/miss reason exposed in response (e.g. "below_threshold" vs "no_candidates")
- [ ] Uptime/version info exposed on /health
- [ ] Correlation between Kafka correlation_id and access logs for full request tracing
- [ ] Cache size (index.ntotal + Redis key count) exposed as a metric

## Deployment & devex
- [ ] GitHub Actions CI (lint + pytest on push)
- [ ] Multi-stage Dockerfile separating build and runtime layers to shrink image size
- [ ] docker-compose healthchecks for Redis and Kafka dependencies
- [ ] .env.example documenting all configuration variables
- [ ] CONTRIBUTING.md
- [ ] Kubernetes manifests (Deployment + Service + ConfigMap) mirroring litekv's k8s/ setup
- [ ] Pre-commit hooks (black + ruff)
- [ ] Makefile with common dev commands (run, test, lint, docker-up)
- [ ] requirements-dev.txt separating dev/test deps from runtime deps
- [ ] LICENSE file (MIT) if missing
- [ ] CODEOWNERS file
- [ ] .dockerignore file to shrink build context

## Security & reliability
- [ ] Max prompt length enforced before embedding to bound compute cost
- [ ] Documented + tested fallback behavior when Redis is unavailable (fail open vs closed)
- [ ] Graceful recovery when the FAISS index file is missing/corrupted on startup
- [ ] Ensure GROQ_API_KEY and other secrets are never logged
- [ ] Timeout + circuit breaker around Groq LLM calls
- [ ] Input sanitization against control chars/ANSI escapes leaking into logs
- [ ] Non-root user in the Docker image
- [ ] Dependency vulnerability scan in CI (pip-audit)

## Docs
- [ ] API usage examples doc with curl + Python snippets for each endpoint
- [ ] Architecture decision record for the two-stage retrieval design choice
- [ ] Benchmark reproduction guide explaining tests/benchmark.py
- [ ] Updated README with a roadmap link and status badges
- [ ] Minimal Python client example wrapping /query
- [ ] Minimal Node.js client example wrapping /query
- [ ] Halfway checkpoint: update README benchmarks + short retrospective
- [ ] Sequence diagram doc for the Kafka request/response flow

## Stretch
- [ ] Streaming responses for cache misses (SSE passthrough from Groq)
- [ ] Thin Python client SDK wrapping the API
- [ ] Minimal admin UI (static HTML hitting /stats and /cache endpoints)
- [ ] Day 100: final benchmark pass + updated numbers + 100-day retrospective
