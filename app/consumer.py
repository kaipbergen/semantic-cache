import asyncio
import json
import os

import redis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.llm import call_llm
from app.kafka_client import (
    KAFKA_BOOTSTRAP_SERVERS,
    LLM_REQUESTS_DLQ_TOPIC,
    LLM_REQUESTS_TOPIC,
    LLM_RESPONSES_TOPIC,
    send_with_retry,
    start_with_retry,
)

# Lightweight client here on purpose: this worker only needs Redis for job
# status, not the bi-encoder/cross-encoder/FAISS stack from app.cache. The
# API process is the sole writer of the FAISS index (see main.py), so this
# worker never touches it.
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
STATUS_TTL_SECONDS = 300
LLM_CALL_MAX_ATTEMPTS = int(os.getenv("LLM_CALL_MAX_ATTEMPTS", 3))
LLM_CALL_RETRY_BASE_DELAY = float(os.getenv("LLM_CALL_RETRY_BASE_DELAY", 0.5))
CONSUMER_GROUP_ID = os.getenv("CONSUMER_GROUP_ID", "llm-worker-group")


async def _call_llm_with_retry(prompt: str) -> str:
    """Retry transient LLM failures with exponential backoff before giving
    up; the caller routes the request to the dead-letter topic once attempts
    are exhausted."""
    last_exc = None
    for attempt in range(1, LLM_CALL_MAX_ATTEMPTS + 1):
        try:
            return await call_llm(prompt)
        except Exception as exc:
            last_exc = exc
            if attempt == LLM_CALL_MAX_ATTEMPTS:
                break
            delay = LLM_CALL_RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(f"[consumer] call_llm failed ({attempt}/{LLM_CALL_MAX_ATTEMPTS}): {exc} - retrying in {delay}s")
            await asyncio.sleep(delay)
    raise last_exc


async def process(producer: AIOKafkaProducer, raw: bytes):
    data = json.loads(raw.decode())
    correlation_id = data["correlation_id"]
    prompt = data["prompt"]

    try:
        response = await _call_llm_with_retry(prompt)
        redis_client.setex(
            f"status:{correlation_id}",
            STATUS_TTL_SECONDS,
            json.dumps({"status": "done", "response": response}),
        )
        payload = {"correlation_id": correlation_id, "prompt": prompt, "response": response}
    except Exception as exc:
        redis_client.setex(
            f"status:{correlation_id}",
            STATUS_TTL_SECONDS,
            json.dumps({"status": "error", "error": str(exc)}),
        )
        payload = {"correlation_id": correlation_id, "prompt": prompt, "error": str(exc)}
        await send_with_retry(
            producer,
            LLM_REQUESTS_DLQ_TOPIC,
            json.dumps(
                {
                    "correlation_id": correlation_id,
                    "prompt": prompt,
                    "error": str(exc),
                    "attempts": LLM_CALL_MAX_ATTEMPTS,
                }
            ).encode(),
        )

    await send_with_retry(producer, LLM_RESPONSES_TOPIC, json.dumps(payload).encode())


async def main():
    consumer = AIOKafkaConsumer(
        LLM_REQUESTS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=CONSUMER_GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)

    await start_with_retry(consumer, "worker-consumer")
    await start_with_retry(producer, "worker-producer")

    print(f"[consumer] listening on '{LLM_REQUESTS_TOPIC}'")
    try:
        async for msg in consumer:
            await process(producer, msg.value)
            await consumer.commit()
    finally:
        await consumer.stop()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
