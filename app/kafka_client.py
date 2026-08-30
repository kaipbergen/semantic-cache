import asyncio
import os

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import KafkaError

from app.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

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
            logger.info("%s connected", name)
            return
        except Exception as exc:
            logger.warning("%s not ready (%d/%d): %s", name, attempt, retries, exc)
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
            logger.warning(
                "Send to '%s' failed (%d/%d): %s - retrying in %ss", topic, attempt, retries, exc, delay
            )
            await asyncio.sleep(delay)


def _compute_lag(end_offsets: dict, committed_offsets: dict) -> dict:
    """end_offsets/committed_offsets are TopicPartition -> int, produced by
    get_consumer_lag. A partition missing from committed_offsets (or with an
    unknown/-1 offset) is treated as never-consumed, i.e. its full backlog
    counts as lag."""
    per_partition = {}
    total = 0
    for tp, end_offset in end_offsets.items():
        committed = committed_offsets.get(tp)
        lag = end_offset if committed is None or committed < 0 else max(end_offset - committed, 0)
        per_partition[tp.partition] = lag
        total += lag
    return {"total_lag": total, "per_partition": per_partition}


async def get_consumer_lag(
    group_id: str, topic: str, bootstrap_servers: str = KAFKA_BOOTSTRAP_SERVERS
) -> dict | None:
    """Best-effort consumer group lag for a topic. Returns None (rather than
    raising) if the topic has no partitions yet or Kafka/group metadata isn't
    reachable, so a Kafka hiccup degrades /stats instead of breaking it."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap_servers)
    try:
        await admin.start()
        await consumer.start()

        topics = await admin.describe_topics([topic])
        if not topics or topics[0].get("error_code") != 0:
            return None
        partitions = [TopicPartition(topic, p["partition"]) for p in topics[0]["partitions"]]
        if not partitions:
            return None

        end_offsets = await consumer.end_offsets(partitions)

        try:
            offsets_response = await admin.list_consumer_group_offsets(group_id, partitions=partitions)
            committed_offsets = {tp: meta.offset for tp, meta in offsets_response.items()}
        except KafkaError:
            # No consumer in this group has ever committed - treat as full lag.
            committed_offsets = {}

        return _compute_lag(end_offsets, committed_offsets)
    except KafkaError:
        return None
    finally:
        await consumer.stop()
        await admin.close()
