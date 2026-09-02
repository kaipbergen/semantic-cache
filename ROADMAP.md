# Semantic Cache — 300 Days of Code

A 300-day roadmap of real, scoped improvements to the LLM semantic cache, executed in
batches by an automated daily task (this project rotates with litekv and projectjava,
5 items per run on its day). Each run: implement the items, verify (tests / smoke test),
commit, push. No filler commits — if an item can't be completed and verified, it stays
unchecked and gets picked up next run.

Progress is tracked by checking items off below (`- [ ]` → `- [x] (Day N, YYYY-MM-DD)`).

## API & endpoints
- [x] Input validation: reject empty/whitespace-only prompts with 400 (Day 2, 2026-07-28)
- [x] Input validation: enforce max prompt length via env var, 413 on overflow (Day 2, 2026-07-28)
- [x] POST /cache/seed to manually insert a prompt→response pair without going through Kafka (Day 2, 2026-07-28)
- [x] GET /cache/entries with pagination to list cached prompts and their TTLs (Day 2, 2026-07-28)
- [x] Rate limiting per client IP (token bucket) on /query (Day 2, 2026-07-28)
- [x] Request correlation ID returned in an X-Request-ID response header (Day 3, 2026-07-30)
- [x] Configurable per-request timeout override via query param on /query (Day 4, 2026-08-01)
- [x] /health deep check: verify Redis ping, FAISS index loaded, Kafka broker reachable (Day 4, 2026-08-01)
- [x] Optional API key auth middleware, enabled via env var (Day 4, 2026-08-01)
- [x] Consistent structured JSON error schema for all HTTPException responses (Day 3, 2026-07-30)
- [x] OPTIONS/CORS preflight support for browser-based clients (Day 4, 2026-08-01)
- [x] Query parameter to bypass cache lookup and force a fresh LLM call (?bypass_cache=true) (Day 4, 2026-08-01)

## Cache core
- [x] Sliding TTL: refresh a cache entry's expiration on hit (Day 3, 2026-07-30)
- [x] Configurable max cache size with LRU eviction of oldest FAISS/prompt_store entries (Day 6, 2026-08-05)
- [x] POST /query/batch for looking up multiple prompts in one call (Day 6, 2026-08-05)
- [x] Prompt normalization: strip emoji/non-ASCII punctuation consistently (Day 5, 2026-08-03)
- [x] Duplicate-prompt guard in store_cache to avoid re-adding an existing prompt to the index (Day 3, 2026-07-30)
- [ ] Per-namespace cache isolation via an optional namespace field on requests
- [x] Configurable bi-encoder model name via env var (Day 5, 2026-08-03)
- [x] Cache warmup script: preload FAISS index + Redis from a JSONL file of prompt/response pairs (Day 6, 2026-08-05)
- [ ] Adaptive threshold auto-tuning based on observed hit/miss outcomes
- [x] Cache entry versioning to support safely swapping embedding models without stale vectors (Day 6, 2026-08-05)
- [x] Response compression for large cached payloads stored in Redis (Day 6, 2026-08-05)
- [x] Configurable cross-encoder model name via env var (Day 5, 2026-08-03)

## Index management
- [x] Atomic FAISS index persistence: write to temp file + rename instead of in-place overwrite (Day 3, 2026-07-30)
- [x] Index compaction command: rebuild the index dropping entries whose Redis TTL has expired (Day 7, 2026-08-07)
- [x] Backup/restore CLI script for the FAISS index + prompt_store (Day 7, 2026-08-07)
- [x] Background task to periodically prune expired entries from prompt_store (Day 7, 2026-08-07)
- [ ] Migration path from IndexFlatIP to IndexIVFFlat for larger-scale recall/perf tradeoff
- [x] Index integrity check on startup (detect prompt_store/index size mismatch) (Day 7, 2026-08-07)
- [x] Configurable index storage path via env var (currently hardcoded /app path) (Day 1, 2026-07-25)
- [x] Export cache contents to JSONL for inspection/debugging (Day 7, 2026-08-07)
- [x] CLI script to rebuild the FAISS index from Redis contents alone (disaster recovery) (Day 8, 2026-08-09)
- [x] Metrics on index size/memory footprint exposed via /stats (Day 5, 2026-08-03)

## Testing
- [x] pytest fixtures providing isolated Redis + FAISS state per test (Day 1, 2026-07-25)
- [x] Unit tests for normalize_query edge cases (punctuation, whitespace, casing) (Day 1, 2026-07-25)
- [x] Unit tests for get_adaptive_threshold pattern matching across categories (Day 1, 2026-07-25)
- [x] Unit tests for get_ttl keyword classification (Day 1, 2026-07-25)
- [x] Integration test: seed cache then assert /query returns a cache hit (Day 8, 2026-08-09)
- [x] Integration test: cache miss path with a mocked Kafka producer/consumer (Day 8, 2026-08-09)
- [x] Integration test: /status/{job_id} polling fallback on timeout (Day 8, 2026-08-09)
- [x] Test coverage reporting via pytest-cov (Day 8, 2026-08-09)
- [x] Regression test for clear_cache endpoint resetting index + Redis together (Day 5, 2026-08-03)
- [x] Load test script (locust or asyncio-based) exercising /query concurrently (Day 10, 2026-08-13)
- [x] Contract test verifying PromptResponse schema stability (Day 10, 2026-08-13)
- [x] CI job matrix testing against two Python versions (Day 10, 2026-08-13)

## Kafka / async pipeline
- [x] Dead-letter topic for LLM requests that fail after N retries (Day 10, 2026-08-13)
- [x] Kafka producer retry with exponential backoff on send_and_wait failures (Day 9, 2026-08-11)
- [x] Idempotent response handling: dedupe on correlation_id if a message is redelivered (Day 10, 2026-08-13)
- [x] Graceful consumer shutdown draining in-flight messages before exit (Day 11, 2026-08-16)
- [x] Kafka consumer lag exposed via /stats (Day 11, 2026-08-16)
- [x] Configurable consumer group ID via env var for horizontal scaling (Day 11, 2026-08-16)
- [x] Poison-message handling: skip and log malformed Kafka payloads instead of crashing the consumer (Day 11, 2026-08-16)
- [ ] Startup readiness check that blocks serving traffic until Kafka topics exist
- [ ] Kafka topic auto-creation with sane partition/replication defaults documented
- [x] Backpressure handling: bound pending_requests size and reject new requests when saturated (Day 11, 2026-08-16)

## Observability
- [x] Prometheus /metrics endpoint (request count, hit rate, latency histograms) (Day 15, 2026-09-02)
- [x] Structured JSON logging with request correlation IDs (Day 14, 2026-08-30)
- [x] /stats breakdown by adaptive-threshold category (factual/definition/explanation) (Day 12, 2026-08-19)
- [x] Slow-query logging for LLM calls exceeding a configurable latency threshold (Day 12, 2026-08-19)
- [ ] Grafana dashboard JSON for the Prometheus metrics
- [x] Request/response logging middleware with configurable verbosity (Day 15, 2026-09-02)
- [ ] /stats historical rollup (hourly buckets) instead of only cumulative counters
- [ ] Sentry or similar error-tracking integration hook (optional, env-gated)
- [x] Cache hit/miss reason exposed in response (e.g. "below_threshold" vs "no_candidates") (Day 9, 2026-08-11)
- [x] Uptime/version info exposed on /health (Day 9, 2026-08-11)
- [ ] Correlation between Kafka correlation_id and access logs for full request tracing
- [x] Cache size (index.ntotal + Redis key count) exposed as a metric (Day 12, 2026-08-19)

## Deployment & devex
- [x] GitHub Actions CI (lint + pytest on push) (Day 15, 2026-09-02)
- [ ] Multi-stage Dockerfile separating build and runtime layers to shrink image size
- [x] docker-compose healthchecks for Redis and Kafka dependencies (Day 13, 2026-08-25)
- [x] .env.example documenting all configuration variables (Day 9, 2026-08-11)
- [x] CONTRIBUTING.md (Day 13, 2026-08-25)
- [ ] Kubernetes manifests (Deployment + Service + ConfigMap) mirroring litekv's k8s/ setup
- [ ] Pre-commit hooks (black + ruff)
- [x] Makefile with common dev commands (run, test, lint, docker-up) (Day 15, 2026-09-02)
- [x] requirements-dev.txt separating dev/test deps from runtime deps (Day 14, 2026-08-30)
- [x] LICENSE file (MIT) if missing (Day 13, 2026-08-25)
- [x] CODEOWNERS file (Day 13, 2026-08-25)
- [x] .dockerignore file to shrink build context (Day 14, 2026-08-30)

## Security & reliability
- [x] Max prompt length enforced before embedding to bound compute cost (Day 13, 2026-08-25)
- [ ] Documented + tested fallback behavior when Redis is unavailable (fail open vs closed)
- [ ] Graceful recovery when the FAISS index file is missing/corrupted on startup
- [x] Ensure GROQ_API_KEY and other secrets are never logged (Day 14, 2026-08-30)
- [x] Timeout + circuit breaker around Groq LLM calls (Day 12, 2026-08-19)
- [x] Input sanitization against control chars/ANSI escapes leaking into logs (Day 14, 2026-08-30)
- [x] Non-root user in the Docker image (Day 9, 2026-08-11)
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
- [x] GET /cache/entries/{prompt_hash} to fetch a single entry's full record (Day 12, 2026-08-19)
- [ ] POST /cache/entries/{prompt_hash}/ttl to manually extend a specific entry's TTL
- [ ] POST /cache/seed/batch for bulk-loading many prompt/response pairs at once
- [ ] "Forget prompt" endpoint that purges a prompt and its cached response entirely
- [ ] Multi-tenant API keys with per-key rate limits, distinct from the global API_KEY
- [ ] Async webhook callback option as an alternative to polling /status/{job_id}
- [ ] Configurable eviction policy choice (LRU vs LFU) instead of LRU-only
- [ ] /stats latency histograms (p50/p95/p99) instead of only averages
- [ ] OpenTelemetry tracing spans across API → Kafka → worker → LLM call
- [ ] Chaos test: simulate a Redis connection drop mid-request, verify graceful fallback
- [ ] Property-based tests (hypothesis) for normalize_query and get_adaptive_threshold
- [ ] docker-compose profile for a full local end-to-end smoke test in CI
- [ ] Automatic scheduled index backup (background task) instead of only the manual CLI script
- [ ] Design doc for sharding the FAISS index across multiple processes for horizontal scale
- [ ] Minimal Go client example wrapping /query
- [ ] Final day: 300-day program retrospective + updated benchmark numbers

## Notes
- Day 6 (2026-08-05): Skipped "Per-namespace cache isolation via an optional
  namespace field on requests" — it requires restructuring prompt_store's
  data model (composite namespace+prompt keys, Redis key format, and every
  consumer of prompt_store: search_cache, list_cache_entries,
  delete_cache_entry, and the new max-cache-size eviction), which is too
  large to land safely as a single scoped item alongside other changes in
  one run. Left unchecked for a future run with more headroom.
- Day 6 (2026-08-05): Skipped "Adaptive threshold auto-tuning based on
  observed hit/miss outcomes" — the system has no ground-truth signal for
  whether a cache hit was actually a correct/relevant answer (no user
  feedback loop exists), so there's no real "observed outcome" to tune
  against yet. Needs a feedback mechanism first; left unchecked.
  "Cache entry versioning" was implemented as index-level versioning
  (persisted bi_encoder_model tag, stale index discarded on mismatch)
  rather than true per-entry versioning, which covers the stated goal
  (avoid stale vectors after swapping embedding models) more simply.
- Day 8 (2026-08-09): Re-confirmed and skipped "Per-namespace cache
  isolation" and "Adaptive threshold auto-tuning" for the same reasons
  as the Day 6 note above (both still hold - prompt_store is still a
  flat list/global Redis keyspace, and there's still no feedback signal
  for tuning). Also skipped "Migration path from IndexFlatIP to
  IndexIVFFlat" without attempting it: IVFFlat requires training,
  differs in how add/remove_ids behave, and _evict_oldest/compact_index
  both assume the IndexFlatIP invariant that positions 0..ntotal-1 stay
  in insertion order - IVFFlat breaks that assumption, so this needs a
  dedicated scoped effort (likely alongside reworking eviction/compaction
  to not rely on positional correspondence) rather than a single-item
  change alongside other work.
- Day 13 (2026-08-25): Checked off "CONTRIBUTING.md" as already-done —
  it was added in commits a81067b/7417ce4 (setup instructions, test
  command, troubleshooting, PR guidelines) but the roadmap line was never
  updated. Verified its content actually satisfies the item before
  checking it off, no new work needed.
