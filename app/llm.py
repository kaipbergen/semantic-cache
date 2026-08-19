import asyncio
import os
import time

from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

LLM_CALL_TIMEOUT_SECONDS = float(os.getenv("LLM_CALL_TIMEOUT_SECONDS", 10))
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5))
CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS = float(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS", 30))


class CircuitOpenError(Exception):
    """Raised instead of calling Groq while the circuit breaker is open."""


class CircuitBreaker:
    """Trips open after `failure_threshold` consecutive failures and rejects
    calls without hitting Groq until `reset_timeout` has passed, then allows
    one half-open trial call to decide whether to close or re-open."""

    def __init__(self, failure_threshold: int, reset_timeout: float):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.state = "closed"
        self.opened_at = None

    def before_call(self):
        if self.state == "open":
            if time.time() - self.opened_at >= self.reset_timeout:
                self.state = "half_open"
            else:
                raise CircuitOpenError("Circuit breaker is open - Groq calls are temporarily suspended")

    def on_success(self):
        self.failure_count = 0
        self.state = "closed"
        self.opened_at = None

    def on_failure(self):
        self.failure_count += 1
        if self.state == "half_open" or self.failure_count >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.time()


circuit_breaker = CircuitBreaker(CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS)


async def call_llm(prompt: str) -> str:
    circuit_breaker.before_call()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=LLM_CALL_TIMEOUT_SECONDS,
        )
    except Exception:
        circuit_breaker.on_failure()
        raise
    circuit_breaker.on_success()
    return response.choices[0].message.content
