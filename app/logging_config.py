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


_configured = False


def configure_logging(level: str | None = None) -> None:
    global _configured
    if _configured:
        return

    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = _StdoutHandler()
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RequestIDFilter())

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [handler]

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
