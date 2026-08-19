import asyncio

import pytest

import app.llm as llm_module
from app.llm import CircuitBreaker, CircuitOpenError, call_llm


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _fake_client(responder):
    class _Completions:
        async def create(self, model, messages):
            return await responder(model, messages)

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return _Client()


@pytest.fixture(autouse=True)
def reset_circuit_breaker(monkeypatch):
    fresh = CircuitBreaker(
        llm_module.CIRCUIT_BREAKER_FAILURE_THRESHOLD, llm_module.CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS
    )
    monkeypatch.setattr(llm_module, "circuit_breaker", fresh)


@pytest.mark.asyncio
async def test_call_llm_returns_response_content(monkeypatch):
    async def responder(model, messages):
        return _FakeResponse("hello there")

    monkeypatch.setattr(llm_module, "client", _fake_client(responder))

    assert await call_llm("hi") == "hello there"


@pytest.mark.asyncio
async def test_call_llm_raises_timeout_error_when_groq_is_slow(monkeypatch):
    async def responder(model, messages):
        await asyncio.sleep(10)
        return _FakeResponse("too slow")

    monkeypatch.setattr(llm_module, "client", _fake_client(responder))
    monkeypatch.setattr(llm_module, "LLM_CALL_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await call_llm("hi")


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold_failures(monkeypatch):
    async def failing_responder(model, messages):
        raise RuntimeError("groq is down")

    monkeypatch.setattr(llm_module, "client", _fake_client(failing_responder))
    monkeypatch.setattr(llm_module.circuit_breaker, "failure_threshold", 2)

    with pytest.raises(RuntimeError):
        await call_llm("hi")
    with pytest.raises(RuntimeError):
        await call_llm("hi")

    with pytest.raises(CircuitOpenError):
        await call_llm("hi")


@pytest.mark.asyncio
async def test_circuit_breaker_does_not_call_groq_while_open(monkeypatch):
    calls = []

    async def failing_responder(model, messages):
        calls.append(1)
        raise RuntimeError("groq is down")

    monkeypatch.setattr(llm_module, "client", _fake_client(failing_responder))
    monkeypatch.setattr(llm_module.circuit_breaker, "failure_threshold", 1)

    with pytest.raises(RuntimeError):
        await call_llm("hi")
    assert len(calls) == 1

    with pytest.raises(CircuitOpenError):
        await call_llm("hi")
    assert len(calls) == 1


def test_circuit_breaker_closes_after_success():
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout=30)
    breaker.on_failure()
    breaker.on_success()
    assert breaker.state == "closed"
    assert breaker.failure_count == 0


def test_circuit_breaker_half_open_reopens_on_repeat_failure():
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=0)
    breaker.on_failure()
    assert breaker.state == "open"

    breaker.before_call()
    assert breaker.state == "half_open"

    breaker.on_failure()
    assert breaker.state == "open"


def test_circuit_breaker_stays_open_before_reset_timeout_elapses():
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=60)
    breaker.on_failure()
    assert breaker.state == "open"

    with pytest.raises(CircuitOpenError):
        breaker.before_call()
