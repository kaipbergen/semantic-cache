import asyncio
import json
import os

import redis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.llm import call_llm
from app.kafka_client import (
    KAFKA_BOOTSTRAP_SERVERS,
    LLM_REQUESTS_TOPIC,
    LLM_RESPONSES_TOPIC,
    start_with_retry,
)

# Lightweight client here on purpose: this worker only needs Redis for job
# status, not the bi-encoder/cross-encoder/FAISS stack from app.cache. The
# API process is the sole writer of the FAISS index (see main.py), so this
# worker never touches it.
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
STATUS_TTL_SECONDS = 300


async def process(producer: AIOKafkaProducer, raw: bytes):
    data = json.loads(raw.decode())
    correlation_id = data["correlation_id"]
    prompt = data["prompt"]

    try:
        response = await call_llm(prompt)
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

    await producer.send_and_wait(LLM_RESPONSES_TOPIC, json.dumps(payload).encode())


async def main():
    consumer = AIOKafkaConsumer(
        LLM_REQUESTS_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id="llm-worker-group",
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
