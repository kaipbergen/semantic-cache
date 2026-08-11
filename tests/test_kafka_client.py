import pytest

from app.kafka_client import send_with_retry


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
