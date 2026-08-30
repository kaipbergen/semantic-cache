import json
import logging

from app.logging_config import JSONFormatter, RequestIDFilter, request_id_var, sanitize_for_log


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
