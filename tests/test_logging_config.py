import json
import logging

from app.logging_config import (
    JSONFormatter,
    RequestIDFilter,
    SecretRedactionFilter,
    _discover_secrets,
    request_id_var,
    sanitize_for_log,
)


def _make_record(**kwargs):
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in kwargs.items():
        setattr(record, key, value)
    return record


def test_json_formatter_produces_valid_json_with_expected_fields():
    record = _make_record(request_id="abc-123")
    formatted = JSONFormatter().format(record)
    payload = json.loads(formatted)

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["request_id"] == "abc-123"


def test_json_formatter_includes_extra_fields():
    record = _make_record(request_id=None, prompt="hi", latency_ms=12.3)
    payload = json.loads(JSONFormatter().format(record))

    assert payload["extra"] == {"prompt": "hi", "latency_ms": 12.3}


def test_json_formatter_omits_extra_key_when_no_extras():
    record = _make_record(request_id=None)
    payload = json.loads(JSONFormatter().format(record))

    assert "extra" not in payload


def test_request_id_filter_reads_contextvar():
    token = request_id_var.set("req-42")
    try:
        record = _make_record()
        assert RequestIDFilter().filter(record) is True
        assert record.request_id == "req-42"
    finally:
        request_id_var.reset(token)


def test_request_id_filter_defaults_to_none_outside_request_context():
    record = _make_record()
    RequestIDFilter().filter(record)
    assert record.request_id is None


def test_sanitize_for_log_leaves_plain_text_untouched():
    assert sanitize_for_log("just a normal prompt") == "just a normal prompt"


def test_sanitize_for_log_escapes_ansi_escape_sequences():
    malicious = "\x1b[31mFAKE ERROR\x1b[0m"
    sanitized = sanitize_for_log(malicious)

    assert "\x1b" not in sanitized
    assert "\\x1b[31mFAKE ERROR\\x1b[0m" == sanitized


def test_sanitize_for_log_escapes_crlf_to_block_log_line_injection():
    injected = "innocent prompt\nlevel=ERROR msg=fake injected line"
    sanitized = sanitize_for_log(injected)

    assert "\n" not in sanitized
    assert sanitized == "innocent prompt\\x0alevel=ERROR msg=fake injected line"


def test_sanitize_for_log_truncates_long_input():
    sanitized = sanitize_for_log("a" * 1000, max_length=50)

    assert sanitized.startswith("a" * 50)
    assert "truncated" in sanitized


def test_sanitize_for_log_coerces_non_string_input():
    assert sanitize_for_log(12345) == "12345"


def test_secret_redaction_filter_redacts_message_containing_secret():
    record = _make_record(msg="calling groq with key sk-super-secret-value", args=())
    filt = SecretRedactionFilter(["sk-super-secret-value"])

    assert filt.filter(record) is True
    assert "sk-super-secret-value" not in record.getMessage()
    assert "***REDACTED***" in record.getMessage()


def test_secret_redaction_filter_redacts_extra_fields():
    record = _make_record(request_id=None, error="auth failed for token abc123secret")
    filt = SecretRedactionFilter(["abc123secret"])

    filt.filter(record)

    assert "abc123secret" not in record.error
    assert record.error == "auth failed for token ***REDACTED***"


def test_secret_redaction_filter_noop_when_no_secrets_configured():
    record = _make_record()
    filt = SecretRedactionFilter([])

    assert filt.filter(record) is True
    assert record.getMessage() == "hello world"


def test_secret_redaction_filter_ignores_falsy_secrets():
    filt = SecretRedactionFilter(["", None, "real-secret-value"])
    assert filt._secrets == ["real-secret-value"]


def test_discover_secrets_picks_up_key_like_env_vars(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-discovered-secret")
    monkeypatch.setenv("SOME_UNRELATED_VAR", "not-a-secret")
    monkeypatch.setenv("SHORT_TOKEN", "abc")

    secrets = _discover_secrets()

    assert "sk-discovered-secret" in secrets
    assert "not-a-secret" not in secrets
    assert "abc" not in secrets
