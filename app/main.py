import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.cache import compact_index, get_stats, redis_client, search_cache, stats, store_cache
from app.consumer import CONSUMER_GROUP_ID
from app.kafka_client import (
    KAFKA_BOOTSTRAP_SERVERS,
    LLM_REQUESTS_TOPIC,
    LLM_RESPONSES_TOPIC,
    get_consumer_lag,
    send_with_retry,
    start_with_retry,
)
from app.logging_config import configure_logging, get_logger, request_id_var, sanitize_for_log
from app.metrics import CONTENT_TYPE_LATEST, REQUEST_LATENCY_SECONDS, render_latest

configure_logging()
logger = get_logger(__name__)

APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
_START_TIME = time.time()

RESPONSE_TIMEOUT_SECONDS = float(os.getenv("RESPONSE_TIMEOUT_SECONDS", 8))
STATUS_TTL_SECONDS = 300
MAX_PROMPT_LENGTH = int(os.getenv("MAX_PROMPT_LENGTH", 4096))
RATE_LIMIT_CAPACITY = float(os.getenv("RATE_LIMIT_CAPACITY", 20))
RATE_LIMIT_REFILL_PER_SECOND = float(os.getenv("RATE_LIMIT_REFILL_PER_SECOND", 5))
MAX_TIMEOUT_OVERRIDE_SECONDS = float(os.getenv("MAX_TIMEOUT_OVERRIDE_SECONDS", 60))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", 50))
MAX_PENDING_REQUESTS = int(os.getenv("MAX_PENDING_REQUESTS", 1000))
CONSUMER_LAG_TIMEOUT_SECONDS = float(os.getenv("CONSUMER_LAG_TIMEOUT_SECONDS", 5))
COMPACTION_INTERVAL_SECONDS = float(os.getenv("COMPACTION_INTERVAL_SECONDS", 0))
SLOW_QUERY_THRESHOLD_MS = float(os.getenv("SLOW_QUERY_THRESHOLD_MS", 5000))
API_KEY = os.getenv("API_KEY")
REQUEST_LOG_VERBOSITY = os.getenv("REQUEST_LOG_VERBOSITY", "basic").lower()
API_KEY_EXEMPT_PATHS = {"/health", "/health/deep", "/docs", "/openapi.json", "/redoc", "/metrics"}
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",") if origin.strip()
]


class TokenBucket:
    def __init__(self, capacity: float, refill_per_second: float):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.tokens = capacity
        self.last_refill = time.time()

    def allow(self) -> bool:
        now = time.time()
        self.tokens = min(self.capacity, self.tokens + (now - self.last_refill) * self.refill_per_second)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


rate_limit_buckets: dict[str, TokenBucket] = {}


def check_rate_limit(client_ip: str):
    bucket = rate_limit_buckets.setdefault(
        client_ip, TokenBucket(RATE_LIMIT_CAPACITY, RATE_LIMIT_REFILL_PER_SECOND)
    )
    if not bucket.allow():
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

producer: AIOKafkaProducer | None = None
# correlation_id -> Future, resolved by consume_responses() when the matching
# message lands on llm-responses. Only meaningful within this process, so this
# request/await path assumes a single API replica (see /status/{job_id} for
# the multi-replica-safe polling fallback).
pending_requests: dict[str, asyncio.Future] = {}


def _mark_response_processed(correlation_id: str) -> bool:
    """Redis SETNX guard: True the first time a correlation_id's response is
    seen, False on a Kafka redelivery of the same message (at-least-once
    delivery can redeliver after a commit races a consumer crash)."""
    return bool(redis_client.set(f"processed:{correlation_id}", "1", nx=True, ex=STATUS_TTL_SECONDS))


def handle_response_message(data: dict):
    correlation_id = data.get("correlation_id")
    is_new = _mark_response_processed(correlation_id) if correlation_id else True

    if "response" in data and is_new:
        # API is the single writer of the in-process FAISS index, so caching
        # always happens here - even for requests that already timed out and
        # got a 202 back. Skipped on a redelivered duplicate so a stale
        # message can't refresh the entry's TTL out of turn.
        store_cache(data["prompt"], data["response"])

    future = pending_requests.pop(correlation_id, None)
    if future and not future.done():
        future.set_result(data)


async def consume_responses():
    consumer = AIOKafkaConsumer(
        LLM_RESPONSES_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="api-response-listener",
        auto_offset_reset="latest",
        enable_auto_commit=True,
    )
    await start_with_retry(consumer, "response-consumer")
    try:
        async for msg in consumer:
            data = json.loads(msg.value.decode())
            handle_response_message(data)
    finally:
        await consumer.stop()


def _prune_once() -> int:
    removed = compact_index()
    if removed:
        logger.info("Pruned %d expired cache entries", removed)
    return removed


async def prune_expired_entries():
    while True:
        await asyncio.sleep(COMPACTION_INTERVAL_SECONDS)
        _prune_once()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await start_with_retry(producer, "producer")
    consumer_task = asyncio.create_task(consume_responses())
    prune_task = asyncio.create_task(prune_expired_entries()) if COMPACTION_INTERVAL_SECONDS > 0 else None
    yield
    consumer_task.cancel()
    if prune_task:
        prune_task.cancel()
    await producer.stop()


app = FastAPI(title="Semantic Cache API", lifespan=lifespan)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if API_KEY and request.url.path not in API_KEY_EXEMPT_PATHS:
            if request.headers.get("X-API-Key") != API_KEY:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": 401, "message": "Invalid or missing API key"}},
                )
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs one line per request. REQUEST_LOG_VERBOSITY controls how much:
    "off" disables it, "basic" (default) logs method/path/status/duration,
    "full" adds query params and client IP. Runs inside RequestIDMiddleware
    so its log line carries the same request_id as everything else."""

    async def dispatch(self, request: Request, call_next):
        if REQUEST_LOG_VERBOSITY == "off":
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000

        extra = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        }
        if REQUEST_LOG_VERBOSITY == "full":
            extra["query_string"] = sanitize_for_log(request.url.query)
            extra["client_ip"] = request.client.host if request.client else None

        logger.info(
            "%s %s -> %d (%.2fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra=extra,
        )
        return response


app.add_middleware(APIKeyMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}},
        headers=exc.headers,
    )


class PromptRequest(BaseModel):
    prompt: str


class PromptResponse(BaseModel):
    response: str | None = None
    cached: bool
    similarity: float | None = None
    latency_ms: float | None = None
    status: str = "done"
    job_id: str | None = None
    cache_reason: str | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "uptime_seconds": round(time.time() - _START_TIME, 3),
    }


@app.get("/health/deep")
async def health_deep():
    from app.cache import index

    checks = {}

    try:
        checks["redis"] = bool(redis_client.ping())
    except Exception as exc:
        checks["redis"] = False
        checks["redis_error"] = str(exc)

    checks["faiss_index"] = index is not None

    checks["kafka"] = False
    if producer is not None:
        try:
            node_id = producer.client.get_random_node()
            checks["kafka"] = node_id is not None and await producer.client.ready(node_id)
        except Exception as exc:
            checks["kafka_error"] = str(exc)

    healthy = checks["redis"] and checks["faiss_index"] and checks["kafka"]
    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if healthy else "unhealthy", "checks": checks},
    )


@app.post("/query", response_model=PromptResponse)
async def query(
    request: PromptRequest,
    http_request: Request,
    timeout: float | None = None,
    bypass_cache: bool = False,
):
    client_ip = http_request.client.host if http_request.client else "unknown"
    check_rate_limit(client_ip)

    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt must not be empty")
    if len(request.prompt) > MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail=f"prompt exceeds max length of {MAX_PROMPT_LENGTH} characters",
        )
    if timeout is not None and not (0 < timeout <= MAX_TIMEOUT_OVERRIDE_SECONDS):
        raise HTTPException(
            status_code=400,
            detail=f"timeout must be > 0 and <= {MAX_TIMEOUT_OVERRIDE_SECONDS} seconds",
        )
    response_timeout = timeout if timeout is not None else RESPONSE_TIMEOUT_SECONDS

    start = time.time()

    cached_response, similarity, cache_reason = (
        (None, None, "bypassed") if bypass_cache else search_cache(request.prompt)
    )

    if cached_response:
        latency = (time.time() - start) * 1000
        stats["total_cached_latency_ms"] += latency
        REQUEST_LATENCY_SECONDS.labels(cache_hit="true").observe(latency / 1000)
        return PromptResponse(
            response=cached_response,
            cached=True,
            similarity=round(float(similarity), 3),
            latency_ms=round(latency, 2),
            cache_reason=cache_reason,
        )

    # Cache miss: hand the LLM call off to Kafka instead of awaiting it directly.
    if len(pending_requests) >= MAX_PENDING_REQUESTS:
        raise HTTPException(
            status_code=503,
            detail="Server is at capacity, please retry shortly",
        )

    correlation_id = str(uuid.uuid4())
    redis_client.setex(
        f"status:{correlation_id}", STATUS_TTL_SECONDS, json.dumps({"status": "processing"})
    )

    future = asyncio.get_event_loop().create_future()
    pending_requests[correlation_id] = future

    await send_with_retry(
        producer,
        LLM_REQUESTS_TOPIC,
        json.dumps({"correlation_id": correlation_id, "prompt": request.prompt}).encode(),
    )

    try:
        data = await asyncio.wait_for(future, timeout=response_timeout)
    except asyncio.TimeoutError:
        pending_requests.pop(correlation_id, None)
        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
                "job_id": correlation_id,
                "cached": False,
                "similarity": round(float(similarity), 3) if similarity else None,
                "cache_reason": cache_reason,
            },
        )

    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])

    latency = (time.time() - start) * 1000
    stats["total_llm_latency_ms"] += latency
    REQUEST_LATENCY_SECONDS.labels(cache_hit="false").observe(latency / 1000)
    if latency > SLOW_QUERY_THRESHOLD_MS:
        logger.warning(
            "Slow LLM call: %.1fms (threshold %.1fms)",
            latency,
            SLOW_QUERY_THRESHOLD_MS,
            extra={"prompt": sanitize_for_log(request.prompt), "latency_ms": round(latency, 1)},
        )
    return PromptResponse(
        response=data["response"],
        cached=False,
        similarity=round(float(similarity), 3) if similarity else None,
        latency_ms=round(latency, 2),
        cache_reason=cache_reason,
    )


class BatchQueryRequest(BaseModel):
    prompts: list[str]


class BatchQueryResult(BaseModel):
    prompt: str
    cached: bool
    response: str | None = None
    similarity: float | None = None
    cache_reason: str | None = None


@app.post("/query/batch", response_model=list[BatchQueryResult])
def query_batch(request: BatchQueryRequest):
    if not request.prompts:
        raise HTTPException(status_code=400, detail="prompts must not be empty")
    if len(request.prompts) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"prompts exceeds max batch size of {MAX_BATCH_SIZE}",
        )

    results = []
    for prompt in request.prompts:
        if not prompt.strip():
            raise HTTPException(status_code=400, detail="prompt must not be empty")
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise HTTPException(
                status_code=413,
                detail=f"prompt exceeds max length of {MAX_PROMPT_LENGTH} characters",
            )
        cached_response, similarity, cache_reason = search_cache(prompt)
        results.append(
            BatchQueryResult(
                prompt=prompt,
                cached=cached_response is not None,
                response=cached_response,
                similarity=round(float(similarity), 3) if similarity is not None else None,
                cache_reason=cache_reason,
            )
        )
    return results


class SeedRequest(BaseModel):
    prompt: str
    response: str


@app.post("/cache/seed", status_code=201)
def seed_cache(request: SeedRequest):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt must not be empty")
    if len(request.prompt) > MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail=f"prompt exceeds max length of {MAX_PROMPT_LENGTH} characters",
        )
    store_cache(request.prompt, request.response)
    return {"message": "Cache entry seeded", "prompt": request.prompt}


@app.get("/cache/entries")
def list_cache_entries(limit: int = 20, offset: int = 0):
    from app.cache import prompt_store

    if limit < 1 or offset < 0:
        raise HTTPException(status_code=400, detail="limit must be >= 1 and offset must be >= 0")

    page = prompt_store[offset : offset + limit]
    entries = [{"prompt": p, "ttl_seconds": redis_client.ttl(p)} for p in page]
    return {"total": len(prompt_store), "limit": limit, "offset": offset, "entries": entries}


@app.get("/cache/entries/{prompt_hash}")
def get_cache_entry(prompt_hash: str):
    from app.cache import _decode_payload, prompt_store

    raw = redis_client.get(prompt_hash)
    if raw is None:
        raise HTTPException(status_code=404, detail="Cache entry not found")
    return {
        "prompt": prompt_hash,
        "response": _decode_payload(raw),
        "ttl_seconds": redis_client.ttl(prompt_hash),
        "indexed": prompt_hash in prompt_store,
    }


@app.get("/status/{job_id}")
def get_job_status(job_id: str):
    raw = redis_client.get(f"status:{job_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(raw)


@app.get("/metrics")
def metrics():
    return Response(content=render_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/stats")
async def get_cache_stats():
    stats_payload = get_stats()
    try:
        stats_payload["consumer_lag"] = await asyncio.wait_for(
            get_consumer_lag(CONSUMER_GROUP_ID, LLM_REQUESTS_TOPIC),
            timeout=CONSUMER_LAG_TIMEOUT_SECONDS,
        )
    except Exception:
        # A Kafka hiccup or slow admin request shouldn't take down /stats -
        # the rest of the cache stats are still meaningful without lag.
        stats_payload["consumer_lag"] = None
    return stats_payload


@app.delete("/cache")
def clear_cache():
    from app.cache import _save_index, index
    index.reset()
    # Reinitialize with correct dimension
    import faiss
    new_index = faiss.IndexFlatIP(768)
    import app.cache as cache_module
    cache_module.index = new_index
    cache_module.prompt_store.clear()
    redis_client.flushdb()
    _save_index(cache_module.index, cache_module.prompt_store)
    return {"message": "Cache cleared", "deleted": "all"}


@app.delete("/cache/{prompt_hash}")
def delete_cache_entry(prompt_hash: str):
    deleted = redis_client.delete(prompt_hash)
    if deleted:
        return {"message": "Deleted cache entry", "key": prompt_hash}
    raise HTTPException(status_code=404, detail="Cache entry not found")
