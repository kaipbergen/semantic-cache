from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

CACHE_LOOKUP_TOTAL = Counter(
    "semantic_cache_lookup_total",
    "Cache lookup outcomes by reason (hit, below_threshold, no_candidates, ...)",
    ["reason"],
)

REQUEST_LATENCY_SECONDS = Histogram(
    "semantic_cache_request_latency_seconds",
    "End-to-end /query latency in seconds, split by whether it was served from cache",
    ["cache_hit"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def render_latest() -> bytes:
    return generate_latest()


__all__ = ["CACHE_LOOKUP_TOTAL", "REQUEST_LATENCY_SECONDS", "render_latest", "CONTENT_TYPE_LATEST"]
