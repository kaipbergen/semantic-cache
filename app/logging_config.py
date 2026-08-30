import json
import logging
import os
import re
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_for_log(value, max_length: int = 500) -> str:
    """Neutralize control characters (including ANSI/CSI escape sequences and
    CR/LF) in untrusted, user-controlled strings before they reach a log
    record, so a crafted prompt can't inject fake log lines or terminal
    escape codes into whatever ends up rendering the logs. Also bounds the
    length so one oversized prompt can't blow up log volume."""
    text = value if isinstance(value, str) else str(value)
    sanitized = _CONTROL_CHAR_RE.sub(lambda m: f"\\x{ord(m.group()):02x}", text)
    if len(sanitized) > max_length:
        omitted = len(sanitized) - max_length
        sanitized = f"{sanitized[:max_length]}...<{omitted} more chars truncated>"
    return sanitized

_RESERVED_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class _StdoutHandler(logging.StreamHandler):
    """Resolves sys.stdout at emit time rather than construction time, so
    test runners that swap sys.stdout per-test (e.g. pytest's capsys) still
    capture log output instead of it going to a stale stream reference."""

    def __init__(self):
        super().__init__(stream=sys.stdout)

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRS and key != "request_id"
        }
        if extras:
            payload["extra"] = extras

        return json.dumps(payload, default=str)


_SECRET_ENV_NAME_RE = re.compile(r"(KEY|SECRET|PASSWORD|TOKEN|CREDENTIAL)", re.IGNORECASE)
_MIN_REDACTED_SECRET_LENGTH = 6
_REDACTED_PLACEHOLDER = "***REDACTED***"


def _discover_secrets() -> list[str]:
    """Any env var whose name looks like it holds a credential (GROQ_API_KEY,
    API_KEY, ...) is treated as a value that must never appear in logs
    verbatim, without needing to hardcode each var by name."""
    return [
        value
        for name, value in os.environ.items()
        if value and len(value) >= _MIN_REDACTED_SECRET_LENGTH and _SECRET_ENV_NAME_RE.search(name)
    ]


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, _REDACTED_PLACEHOLDER)
    return text


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True

        record.msg = _redact(record.getMessage(), self._secrets)
        record.args = ()

        for key, value in list(record.__dict__.items()):
            if key in _RESERVED_RECORD_ATTRS or key == "request_id" or not isinstance(value, str):
                continue
            record.__dict__[key] = _redact(value, self._secrets)

        return True


_configured = False


def configure_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return

    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = _StdoutHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RequestIDFilter())
    handler.addFilter(SecretRedactionFilter(_discover_secrets()))

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [handler]

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
