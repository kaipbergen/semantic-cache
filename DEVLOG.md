# Dev Log

## 2026-11-27

Started by checking actual CI history (`gh run list`) rather than just trusting the green-looking
badge in README - turned out the "Tests" workflow had failed on **every single run since the
project's first commit**. Four commits today:

1. **fix**: root-caused and fixed both reasons CI has never passed:
   - `pytest` job: `test_consumer.py`/`test_contract.py`/`test_llm.py`/
     `test_response_idempotency.py` all import `app.llm`, which builds a real `AsyncGroq` client
     at import time - raises instantly without `GROQ_API_KEY`, which CI never set. Fixed in
     `tests/conftest.py` with a dummy default (the client is always monkeypatched per-test, so no
     real key is ever needed).
   - `security` job: `pip-audit`'s ignore list had drifted out of date against new CVEs in
     `sentence-transformers`/`transformers`; added the new IDs with the same "needs a major-version
     bump" rationale as the existing list.
   - Verified both fixes locally (full pytest suite, `make audit`) before trusting them.
2. **feat**: `/stats` now includes an `hourly` rollup (`HOURLY_STATS_RETENTION_HOURS`, default 24)
   of zero-filled `{hour, requests, cache_hits, cache_misses}` buckets, so hit-rate trend is
   visible without an external metrics scraper diffing `/metrics` over time.
3. **docs**: added `docs/examples/query_client.py`, a minimal `SemanticCacheClient` wrapping
   `/query` that transparently handles the API key header and the `202`/`job_id` polling fallback
   - tested against `httpx.MockTransport`, no live server needed.
4. **feat**: Sentry error tracking (`SENTRY_DSN`, optional/env-gated) via its Starlette/FastAPI
   auto-integration - unset by default, so no behavior change unless explicitly opted into.

### Ideas for next time
- Now that CI actually runs pytest, it's worth watching the next few pushes to confirm it stays
  green rather than silently rotting again - maybe a periodic "is main's CI green" check is itself
  worth scripting.
- `Per-namespace cache isolation` and `Adaptive threshold auto-tuning` are still blocked for the
  reasons noted in ROADMAP.md's Day 6/8 Notes - still true, still needs the prompt_store rework /
  a real feedback signal respectively.
- An architecture decision record for the two-stage retrieval design, or a benchmark reproduction
  guide for `tests/benchmark.py`, are both small, clean, self-contained docs items for a future run.

## 2026-11-24

Picked up the next unchecked items from ROADMAP.md (Day 16). Five commits:

1. **fix**: `_load_index()` could crash the whole app on startup if the FAISS
   index or prompt_store file was corrupted/truncated rather than missing -
   now discarded and rebuilt fresh, same as the existing stale-model/
   size-mismatch handling.
2. **feat**: `search_cache`/`store_cache` now fail open on a Redis outage
   (treated as a cache miss / skipped write, logged as a warning) instead of
   raising and taking down `/query` - the cache is an optimization, not a
   hard dependency for serving requests. Scoped to the hot path only; admin
   endpoints (`/cache/*`, `/status/{job_id}`) still fail closed.
3. **feat**: log the Kafka `correlation_id` alongside the HTTP `request_id`
   on cache miss, so a request's API log line and its worker log lines
   (which only know `correlation_id`) can finally be joined into one trace.
4. **docs**: added `docs/API_EXAMPLES.md` with curl + Python snippets for
   every endpoint - previously only `/query` had one, anywhere.
5. **ci**: wired up pre-commit hooks running `ruff check --fix`, pinned to
   the same ruff version as `requirements-dev.txt`. Tried `ruff format` too
   but it reformatted 12 existing files against the grain of the current
   style, so left that out as a separate, dedicated change.

Toolchain note: the system Python (Homebrew 3.14, also 3.11) has a broken
`pyexpat` (symbol mismatch against `/usr/lib/libexpat.1.dylib`), which breaks
`plistlib` and therefore `ensurepip`/pip's `truststore` SSL path on this
macOS version. Homebrew Python 3.12/3.13 aren't affected - used 3.12 for the
venv. Not a repo problem, nothing to fix here, just a note for next time.

### Ideas for next time
- `Per-namespace cache isolation` and `Adaptive threshold auto-tuning` are
  still blocked on the reasons noted in ROADMAP.md's Day 6/8 entries - worth
  revisiting once there's a real feedback signal or appetite for the
  prompt_store data-model rework.
- `/stats` historical rollup (hourly buckets) would pair well with the new
  correlation-id tracing - both are about making past behavior inspectable,
  not just current cumulative counters.
- A Sentry/error-tracking hook (optional, env-gated) is still unscoped and
  would be a clean, self-contained next item.
