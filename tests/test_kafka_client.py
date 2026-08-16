import pytest
from aiokafka import TopicPartition
from aiokafka.errors import KafkaError
from aiokafka.structs import OffsetAndMetadata

from app.kafka_client import _compute_lag, get_consumer_lag, send_with_retry


class _FlakyProducer:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def send_and_wait(self, topic, value):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("broker unavailable")
        return "sent"


@pytest.mark.asyncio
async def test_send_with_retry_succeeds_after_transient_failures(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.kafka_client.asyncio.sleep", fake_sleep)

    producer = _FlakyProducer(fail_times=2)
    result = await send_with_retry(producer, "topic", b"value", retries=5, base_delay=0.1)

    assert result == "sent"
    assert producer.calls == 3
    assert sleeps == [0.1, 0.2]


@pytest.mark.asyncio
async def test_send_with_retry_raises_after_exhausting_retries(monkeypatch):
    async def fake_sleep(delay):
        pass

    monkeypatch.setattr("app.kafka_client.asyncio.sleep", fake_sleep)

    producer = _FlakyProducer(fail_times=10)

    with pytest.raises(ConnectionError):
        await send_with_retry(producer, "topic", b"value", retries=3, base_delay=0.1)

    assert producer.calls == 3


@pytest.mark.asyncio
async def test_send_with_retry_succeeds_immediately_without_sleeping(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.kafka_client.asyncio.sleep", lambda d: sleeps.append(d))

    producer = _FlakyProducer(fail_times=0)
    result = await send_with_retry(producer, "topic", b"value")

    assert result == "sent"
    assert producer.calls == 1
    assert sleeps == []


def test_compute_lag_sums_per_partition_difference():
    tp0 = TopicPartition("llm-requests", 0)
    tp1 = TopicPartition("llm-requests", 1)

    result = _compute_lag(
        end_offsets={tp0: 10, tp1: 5},
        committed_offsets={tp0: 7, tp1: 5},
    )

    assert result == {"total_lag": 3, "per_partition": {0: 3, 1: 0}}


def test_compute_lag_treats_missing_or_unknown_commit_as_full_backlog():
    tp0 = TopicPartition("llm-requests", 0)

    result = _compute_lag(end_offsets={tp0: 42}, committed_offsets={})
    assert result == {"total_lag": 42, "per_partition": {0: 42}}

    result = _compute_lag(end_offsets={tp0: 42}, committed_offsets={tp0: -1})
    assert result == {"total_lag": 42, "per_partition": {0: 42}}


class _FakeAdmin:
    def __init__(self, describe_topics_result, offsets_result=None, offsets_error=None, **kwargs):
        self._describe_topics_result = describe_topics_result
        self._offsets_result = offsets_result
        self._offsets_error = offsets_error

    async def start(self):
        pass

    async def close(self):
        pass

    async def describe_topics(self, topics):
        return self._describe_topics_result

    async def list_consumer_group_offsets(self, group_id, partitions=None):
        if self._offsets_error:
            raise self._offsets_error
        return self._offsets_result


class _FakeLagConsumer:
    def __init__(self, end_offsets_result, **kwargs):
        self._end_offsets_result = end_offsets_result

    async def start(self):
        pass

    async def stop(self):
        pass

    async def end_offsets(self, partitions):
        return self._end_offsets_result


@pytest.mark.asyncio
async def test_get_consumer_lag_returns_total_and_per_partition(monkeypatch):
    tp0 = TopicPartition("llm-requests", 0)
    describe_result = [{"error_code": 0, "partitions": [{"partition": 0}]}]
    end_offsets = {tp0: 10}
    offsets_result = {tp0: OffsetAndMetadata(offset=6, metadata="")}

    monkeypatch.setattr(
        "app.kafka_client.AIOKafkaAdminClient",
        lambda **kwargs: _FakeAdmin(describe_result, offsets_result),
    )
    monkeypatch.setattr(
        "app.kafka_client.AIOKafkaConsumer",
        lambda **kwargs: _FakeLagConsumer(end_offsets),
    )

    result = await get_consumer_lag("llm-worker-group", "llm-requests")
    assert result == {"total_lag": 4, "per_partition": {0: 4}}


@pytest.mark.asyncio
async def test_get_consumer_lag_returns_none_when_topic_missing(monkeypatch):
    monkeypatch.setattr(
        "app.kafka_client.AIOKafkaAdminClient",
        lambda **kwargs: _FakeAdmin([{"error_code": 3, "partitions": []}]),
    )
    monkeypatch.setattr(
        "app.kafka_client.AIOKafkaConsumer",
        lambda **kwargs: _FakeLagConsumer({}),
    )

    result = await get_consumer_lag("llm-worker-group", "no-such-topic")
    assert result is None


@pytest.mark.asyncio
async def test_get_consumer_lag_treats_never_committed_group_as_full_lag(monkeypatch):
    tp0 = TopicPartition("llm-requests", 0)
    describe_result = [{"error_code": 0, "partitions": [{"partition": 0}]}]
    end_offsets = {tp0: 7}

    monkeypatch.setattr(
        "app.kafka_client.AIOKafkaAdminClient",
        lambda **kwargs: _FakeAdmin(describe_result, offsets_error=KafkaError("no coordinator")),
    )
    monkeypatch.setattr(
        "app.kafka_client.AIOKafkaConsumer",
        lambda **kwargs: _FakeLagConsumer(end_offsets),
    )

    result = await get_consumer_lag("brand-new-group", "llm-requests")
    assert result == {"total_lag": 7, "per_partition": {0: 7}}
