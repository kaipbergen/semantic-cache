# Semantic Cache — 100 Days of Code

A 100-day roadmap of real, scoped improvements to the LLM semantic cache, executed in
batches by an automated daily task (this project runs on alternating days, 5 items per run).
Each run: implement the items, verify (tests / smoke test), commit, push. No filler commits —
if an item can't be completed and verified, it stays unchecked and gets picked up next run.

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
- [x] Cache hit/miss reason exposed in response (e.g. "below_threshold" vs "no_candidates") (Day 9, 2026-08-11)
- [x] Uptime/version info exposed on /health (Day 9, 2026-08-11)
- [ ] Correlation between Kafka correlation_id and access logs for full request tracing
- [ ] Cache size (index.ntotal + Redis key count) exposed as a metric

## Deployment & devex
- [ ] GitHub Actions CI (lint + pytest on push)
- [ ] Multi-stage Dockerfile separating build and runtime layers to shrink image size
- [ ] docker-compose healthchecks for Redis and Kafka dependencies
- [x] .env.example documenting all configuration variables (Day 9, 2026-08-11)
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
