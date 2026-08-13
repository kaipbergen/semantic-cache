import asyncio
import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
LLM_REQUESTS_TOPIC = "llm-requests"
LLM_RESPONSES_TOPIC = "llm-responses"
LLM_REQUESTS_DLQ_TOPIC = "llm-requests-dlq"


async def start_with_retry(client, name: str, retries: int = 15, delay: float = 3.0):
    """Kafka takes a few seconds to accept connections after container start;
    retry instead of failing the whole service on first boot."""
    for attempt in range(1, retries + 1):
        try:
            await client.start()
            print(f"[kafka] {name} connected")
            return
        except Exception as exc:
            print(f"[kafka] {name} not ready ({attempt}/{retries}): {exc}")
            await asyncio.sleep(delay)
    raise RuntimeError(f"Could not start {name} after {retries} attempts")


async def send_with_retry(producer, topic: str, value: bytes, retries: int = 5, base_delay: float = 0.5):
    """send_and_wait can fail on transient broker issues (leader election,
    temporary unavailability); retry with exponential backoff instead of
    failing the caller's request outright."""
    for attempt in range(1, retries + 1):
        try:
            return await producer.send_and_wait(topic, value)
        except Exception as exc:
            if attempt == retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(f"[kafka] send to '{topic}' failed ({attempt}/{retries}): {exc} - retrying in {delay}s")
            await asyncio.sleep(delay)
