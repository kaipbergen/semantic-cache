import asyncio
import json
import types

import pytest

from app.kafka_client import LLM_REQUESTS_DLQ_TOPIC, LLM_RESPONSES_TOPIC
from app.consumer import _consume_loop, process


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


class _FakePolledConsumer:
    def __init__(self, messages):
        self._messages = messages
        self.calls = 0
        self.committed = 0

    async def getone(self):
        msg = self._messages[self.calls]
        self.calls += 1
        return types.SimpleNamespace(value=msg)

    async def commit(self):
        self.committed += 1


@pytest.mark.asyncio
async def test_consume_loop_drains_in_flight_message_before_exiting_on_shutdown(monkeypatch):
    import app.consumer as consumer_module

    messages = [
        json.dumps({"correlation_id": "a", "prompt": "hi"}).encode(),
        json.dumps({"correlation_id": "b", "prompt": "hi2"}).encode(),
    ]
    shutdown_event = asyncio.Event()
    processed = []

    async def fake_process(producer, raw):
        processed.append(raw)
        # Simulate a shutdown signal arriving while this message is still
        # being processed - the loop must finish it (and commit) rather
        # than abandoning it mid-flight.
        shutdown_event.set()

    monkeypatch.setattr(consumer_module, "process", fake_process)

    consumer = _FakePolledConsumer(messages)
    await consumer_module._consume_loop(consumer, producer=None, shutdown_event=shutdown_event)

    assert processed == [messages[0]]
    assert consumer.committed == 1
    assert consumer.calls == 1


@pytest.mark.asyncio
async def test_consume_loop_exits_promptly_when_idle_and_shutdown_requested(monkeypatch):
    import app.consumer as consumer_module

    class _NeverReadyConsumer:
        async def getone(self):
            await asyncio.sleep(10)

        async def commit(self):
            pass

    processed = []

    async def fake_process(producer, raw):
        processed.append(raw)

    monkeypatch.setattr(consumer_module, "process", fake_process)

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await asyncio.wait_for(
        consumer_module._consume_loop(_NeverReadyConsumer(), producer=None, shutdown_event=shutdown_event, poll_timeout=0.01),
        timeout=1.0,
    )

    assert processed == []


def test_consumer_group_id_defaults_to_llm_worker_group(monkeypatch):
    import importlib

    import app.consumer as consumer_module

    monkeypatch.delenv("CONSUMER_GROUP_ID", raising=False)
    importlib.reload(consumer_module)
    try:
        assert consumer_module.CONSUMER_GROUP_ID == "llm-worker-group"
    finally:
        importlib.reload(consumer_module)


def test_consumer_group_id_is_configurable_via_env_var(monkeypatch):
    import importlib

    import app.consumer as consumer_module

    monkeypatch.setenv("CONSUMER_GROUP_ID", "llm-worker-group-2")
    importlib.reload(consumer_module)
    try:
        assert consumer_module.CONSUMER_GROUP_ID == "llm-worker-group-2"
    finally:
        monkeypatch.delenv("CONSUMER_GROUP_ID", raising=False)
        importlib.reload(consumer_module)


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
