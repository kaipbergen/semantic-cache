# Dev Log

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
