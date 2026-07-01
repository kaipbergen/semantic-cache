import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.cache import search_cache, store_cache, get_stats, stats, redis_client
from app.kafka_client import (
    KAFKA_BOOTSTRAP_SERVERS,
    LLM_REQUESTS_TOPIC,
    LLM_RESPONSES_TOPIC,
    start_with_retry,
)

RESPONSE_TIMEOUT_SECONDS = float(os.getenv("RESPONSE_TIMEOUT_SECONDS", 8))
STATUS_TTL_SECONDS = 300

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


@app.post("/query", response_model=PromptResponse)
async def query(request: PromptRequest):
    start = time.time()

    cached_response, similarity = search_cache(request.prompt)

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
        data = await asyncio.wait_for(future, timeout=RESPONSE_TIMEOUT_SECONDS)
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
