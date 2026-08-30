import asyncio
import json
import os
import signal

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
from app.logging_config import configure_logging, get_logger, request_id_var

configure_logging()
logger = get_logger(__name__)

# Lightweight client here on purpose: this worker only needs Redis for job
# status, not the bi-encoder/cross-encoder/FAISS stack from app.cache. The
# API process is the sole writer of the FAISS index (see main.py), so this
# worker never touches it.
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
STATUS_TTL_SECONDS = 300
LLM_CALL_MAX_ATTEMPTS = int(os.getenv("LLM_CALL_MAX_ATTEMPTS", 3))
LLM_CALL_RETRY_BASE_DELAY = float(os.getenv("LLM_CALL_RETRY_BASE_DELAY", 0.5))
CONSUMER_GROUP_ID = os.getenv("CONSUMER_GROUP_ID", "llm-worker-group")
CONSUMER_SHUTDOWN_POLL_SECONDS = float(os.getenv("CONSUMER_SHUTDOWN_POLL_SECONDS", 1.0))


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
            logger.warning(
                "call_llm failed (%d/%d): %s - retrying in %ss",
                attempt,
                LLM_CALL_MAX_ATTEMPTS,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise last_exc


async def process(producer: AIOKafkaProducer, raw: bytes):
    try:
        data = json.loads(raw.decode())
        correlation_id = data["correlation_id"]
        prompt = data["prompt"]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        # A malformed payload can never succeed on retry, so log and drop it
        # rather than raising - an uncaught exception here would crash the
        # whole consume loop and stop all other messages from being processed.
        logger.error(
            "Skipping malformed message (%s: %s)", exc.__class__.__name__, exc, extra={"raw": repr(raw)}
        )
        return

    token = request_id_var.set(correlation_id)
    try:
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
    finally:
        request_id_var.reset(token)


async def _consume_loop(consumer, producer, shutdown_event: asyncio.Event, poll_timeout: float = 1.0):
    """Poll for messages instead of `async for msg in consumer` so a pending
    shutdown is noticed between messages even while idle, but a message
    already being processed always runs to completion (process + commit)
    before the loop re-checks shutdown_event and exits."""
    while not shutdown_event.is_set():
        try:
            msg = await asyncio.wait_for(consumer.getone(), timeout=poll_timeout)
        except asyncio.TimeoutError:
            continue
        await process(producer, msg.value)
        await consumer.commit()


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

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            # add_signal_handler is unsupported on some platforms (e.g. Windows).
            pass

    logger.info("Listening on '%s'", LLM_REQUESTS_TOPIC)
    try:
        await _consume_loop(consumer, producer, shutdown_event, CONSUMER_SHUTDOWN_POLL_SECONDS)
        logger.info("Shutdown signal received, drained in-flight work - exiting")
    finally:
        await consumer.stop()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
