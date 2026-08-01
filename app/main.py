import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.cache import search_cache, store_cache, get_stats, stats, redis_client
from app.kafka_client import (
    KAFKA_BOOTSTRAP_SERVERS,
    LLM_REQUESTS_TOPIC,
    LLM_RESPONSES_TOPIC,
    start_with_retry,
)

RESPONSE_TIMEOUT_SECONDS = float(os.getenv("RESPONSE_TIMEOUT_SECONDS", 8))
STATUS_TTL_SECONDS = 300
MAX_PROMPT_LENGTH = int(os.getenv("MAX_PROMPT_LENGTH", 4096))
RATE_LIMIT_CAPACITY = float(os.getenv("RATE_LIMIT_CAPACITY", 20))
RATE_LIMIT_REFILL_PER_SECOND = float(os.getenv("RATE_LIMIT_REFILL_PER_SECOND", 5))
MAX_TIMEOUT_OVERRIDE_SECONDS = float(os.getenv("MAX_TIMEOUT_OVERRIDE_SECONDS", 60))
API_KEY = os.getenv("API_KEY")
API_KEY_EXEMPT_PATHS = {"/health", "/health/deep", "/docs", "/openapi.json", "/redoc"}
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
            correlation_id = data.get("correlation_id")

            if "response" in data:
                # API is the single writer of the in-process FAISS index, so
                # caching always happens here - even for requests that already
                # timed out and got a 202 back.
                store_cache(data["prompt"], data["response"])

            future = pending_requests.pop(correlation_id, None)
            if future and not future.done():
                future.set_result(data)
    finally:
        await consumer.stop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    await start_with_retry(producer, "producer")
    consumer_task = asyncio.create_task(consume_responses())
    yield
    consumer_task.cancel()
    await producer.stop()


app = FastAPI(title="Semantic Cache API", lifespan=lifespan)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
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


app.add_middleware(APIKeyMiddleware)
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


@app.get("/health")
def health():
    return {"status": "ok"}


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

    cached_response, similarity = (None, None) if bypass_cache else search_cache(request.prompt)

    if cached_response:
        latency = (time.time() - start) * 1000
        stats["total_cached_latency_ms"] += latency
        return PromptResponse(
            response=cached_response,
            cached=True,
            similarity=round(float(similarity), 3),
            latency_ms=round(latency, 2),
        )

    # Cache miss: hand the LLM call off to Kafka instead of awaiting it directly.
    correlation_id = str(uuid.uuid4())
    redis_client.setex(
        f"status:{correlation_id}", STATUS_TTL_SECONDS, json.dumps({"status": "processing"})
    )

    future = asyncio.get_event_loop().create_future()
    pending_requests[correlation_id] = future

    await producer.send_and_wait(
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
            },
        )

    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"])

    latency = (time.time() - start) * 1000
    stats["total_llm_latency_ms"] += latency
    return PromptResponse(
        response=data["response"],
        cached=False,
        similarity=round(float(similarity), 3) if similarity else None,
        latency_ms=round(latency, 2),
    )


class SeedRequest(BaseModel):
    prompt: str
    response: str


@app.post("/cache/seed", status_code=201)
def seed_cache(request: SeedRequest):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt must not be empty")
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


@app.get("/status/{job_id}")
def get_job_status(job_id: str):
    raw = redis_client.get(f"status:{job_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(raw)


@app.get("/stats")
def get_cache_stats():
    return get_stats()


@app.delete("/cache")
def clear_cache():
    from app.cache import index, prompt_store, _save_index
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
