import json

import pytest

from app.kafka_client import LLM_REQUESTS_DLQ_TOPIC, LLM_RESPONSES_TOPIC
from app.consumer import process


class _FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, value):
        self.sent.append((topic, value))


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = value


@pytest.mark.asyncio
async def test_process_publishes_response_and_no_dlq_message_on_success(monkeypatch):
    import app.consumer as consumer_module

    fake_redis = _FakeRedis()
    monkeypatch.setattr(consumer_module, "redis_client", fake_redis)

    async def fake_call_llm(prompt):
        return "an answer"

    monkeypatch.setattr(consumer_module, "call_llm", fake_call_llm)

    producer = _FakeProducer()
    raw = json.dumps({"correlation_id": "abc", "prompt": "hello"}).encode()
    await process(producer, raw)

    topics_sent = [topic for topic, _ in producer.sent]
    assert topics_sent == [LLM_RESPONSES_TOPIC]

    response_payload = json.loads(producer.sent[0][1].decode())
    assert response_payload == {"correlation_id": "abc", "prompt": "hello", "response": "an answer"}
    assert json.loads(fake_redis.store["status:abc"])["status"] == "done"


@pytest.mark.asyncio
async def test_process_retries_transient_failures_then_succeeds(monkeypatch):
    import app.consumer as consumer_module

    monkeypatch.setattr(consumer_module, "redis_client", _FakeRedis())
    monkeypatch.setattr(consumer_module, "LLM_CALL_MAX_ATTEMPTS", 3)

    async def fake_sleep(delay):
        pass

    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)

    calls = {"count": 0}

    async def flaky_call_llm(prompt):
        calls["count"] += 1
        if calls["count"] < 3:
            raise ConnectionError("transient")
        return "recovered answer"

    monkeypatch.setattr(consumer_module, "call_llm", flaky_call_llm)

    producer = _FakeProducer()
    raw = json.dumps({"correlation_id": "xyz", "prompt": "hello"}).encode()
    await process(producer, raw)

    assert calls["count"] == 3
    topics_sent = [topic for topic, _ in producer.sent]
    assert topics_sent == [LLM_RESPONSES_TOPIC]
    response_payload = json.loads(producer.sent[0][1].decode())
    assert response_payload["response"] == "recovered answer"


@pytest.mark.asyncio
async def test_process_sends_to_dead_letter_topic_after_exhausting_retries(monkeypatch):
    import app.consumer as consumer_module

    fake_redis = _FakeRedis()
    monkeypatch.setattr(consumer_module, "redis_client", fake_redis)
    monkeypatch.setattr(consumer_module, "LLM_CALL_MAX_ATTEMPTS", 2)

    async def fake_sleep(delay):
        pass

    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)

    async def always_fails(prompt):
        raise RuntimeError("llm is down")

    monkeypatch.setattr(consumer_module, "call_llm", always_fails)

    producer = _FakeProducer()
    raw = json.dumps({"correlation_id": "dead-1", "prompt": "hello"}).encode()
    await process(producer, raw)

    topics_sent = [topic for topic, _ in producer.sent]
    assert topics_sent == [LLM_REQUESTS_DLQ_TOPIC, LLM_RESPONSES_TOPIC]

    dlq_payload = json.loads(producer.sent[0][1].decode())
    assert dlq_payload == {
        "correlation_id": "dead-1",
        "prompt": "hello",
        "error": "llm is down",
        "attempts": 2,
    }

    response_payload = json.loads(producer.sent[1][1].decode())
    assert response_payload == {"correlation_id": "dead-1", "prompt": "hello", "error": "llm is down"}
    assert json.loads(fake_redis.store["status:dead-1"])["status"] == "error"


@pytest.mark.asyncio
async def test_call_llm_with_retry_raises_the_last_exception(monkeypatch):
    import app.consumer as consumer_module

    monkeypatch.setattr(consumer_module, "LLM_CALL_MAX_ATTEMPTS", 3)

    async def fake_sleep(delay):
        pass

    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)

    attempts = []

    async def always_fails(prompt):
        attempts.append(1)
        raise ValueError(f"fail {len(attempts)}")

    monkeypatch.setattr(consumer_module, "call_llm", always_fails)

    with pytest.raises(ValueError, match="fail 3"):
        await consumer_module._call_llm_with_retry("prompt")

    assert len(attempts) == 3
