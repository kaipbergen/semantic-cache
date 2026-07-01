import asyncio
import os

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
LLM_REQUESTS_TOPIC = "llm-requests"
LLM_RESPONSES_TOPIC = "llm-responses"


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
