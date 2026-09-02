import json


def _request_logs(captured_out, path):
    lines = [json.loads(line) for line in captured_out.splitlines() if line.strip().startswith("{")]
    return [line for line in lines if line.get("extra", {}).get("path") == path]


def test_basic_verbosity_logs_method_path_status_and_duration(api_client, capsys):
    response = api_client.get("/health")
    assert response.status_code == 200

    captured = capsys.readouterr()
    logs = _request_logs(captured.out, "/health")
    assert len(logs) == 1
    entry = logs[0]
    assert entry["extra"]["method"] == "GET"
    assert entry["extra"]["status_code"] == 200
    assert isinstance(entry["extra"]["duration_ms"], (int, float))
    assert "query_string" not in entry["extra"]
    assert entry["request_id"]


def test_verbosity_off_disables_request_logging(api_client, monkeypatch, capsys):
    import app.main as main_module

    monkeypatch.setattr(main_module, "REQUEST_LOG_VERBOSITY", "off")

    response = api_client.get("/health")
    assert response.status_code == 200

    captured = capsys.readouterr()
    assert _request_logs(captured.out, "/health") == []


def test_full_verbosity_includes_query_string_and_client_ip(api_client, monkeypatch, capsys):
    import app.main as main_module

    monkeypatch.setattr(main_module, "REQUEST_LOG_VERBOSITY", "full")

    response = api_client.get("/cache/entries?limit=5&offset=0")
    assert response.status_code == 200

    captured = capsys.readouterr()
    logs = _request_logs(captured.out, "/cache/entries")
    assert len(logs) == 1
    entry = logs[0]
    assert entry["extra"]["query_string"] == "limit=5&offset=0"
    assert "client_ip" in entry["extra"]


def test_full_verbosity_sanitizes_control_chars_in_query_string(api_client, monkeypatch, capsys):
    import app.main as main_module

    monkeypatch.setattr(main_module, "REQUEST_LOG_VERBOSITY", "full")

    response = api_client.get("/health", params={"x": "a\nb"})
    assert response.status_code == 200

    captured = capsys.readouterr()
    logs = _request_logs(captured.out, "/health")
    assert len(logs) == 1
    assert "\n" not in logs[0]["extra"]["query_string"]


def test_request_logging_captures_rejected_requests(api_client, monkeypatch, capsys):
    import app.main as main_module

    monkeypatch.setattr(main_module, "API_KEY", "secret-key")

    response = api_client.get("/cache/entries")
    assert response.status_code == 401

    captured = capsys.readouterr()
    logs = _request_logs(captured.out, "/cache/entries")
    assert len(logs) == 1
    assert logs[0]["extra"]["status_code"] == 401
