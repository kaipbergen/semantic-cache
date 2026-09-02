import asyncio

import app.main as main_module


def _setup(isolated_cache, monkeypatch):
    monkeypatch.setattr(main_module, "redis_client", isolated_cache)
    monkeypatch.setattr(main_module, "pending_requests", {})
    return main_module


def test_handle_response_message_stores_cache_and_resolves_future(isolated_cache, monkeypatch):
    import app.cache as cache_module

    mod = _setup(isolated_cache, monkeypatch)
    future = asyncio.get_event_loop().create_future()
    mod.pending_requests["corr-1"] = future

    mod.handle_response_message({"correlation_id": "corr-1", "prompt": "hi", "response": "hello"})

    assert future.result() == {"correlation_id": "corr-1", "prompt": "hi", "response": "hello"}
    assert "corr-1" not in mod.pending_requests
    assert cache_module.prompt_store == ["hi"]


def test_handle_response_message_skips_duplicate_store_cache_on_redelivery(isolated_cache, monkeypatch):

    mod = _setup(isolated_cache, monkeypatch)

    calls = []
    monkeypatch.setattr(mod, "store_cache", lambda prompt, response: calls.append((prompt, response)))

    data = {"correlation_id": "corr-2", "prompt": "hi", "response": "hello"}
    mod.handle_response_message(data)
    # Simulate Kafka at-least-once redelivery of the same message.
    mod.handle_response_message(data)

    assert calls == [("hi", "hello")]


def test_handle_response_message_still_resolves_pending_future_on_redelivery(isolated_cache, monkeypatch):
    mod = _setup(isolated_cache, monkeypatch)
    monkeypatch.setattr(mod, "store_cache", lambda prompt, response: None)

    data = {"correlation_id": "corr-3", "prompt": "hi", "response": "hello"}
    mod.handle_response_message(data)

    future = asyncio.get_event_loop().create_future()
    mod.pending_requests["corr-3"] = future
    mod.handle_response_message(data)

    assert future.result() == data


def test_handle_response_message_handles_missing_correlation_id_gracefully(isolated_cache, monkeypatch):
    mod = _setup(isolated_cache, monkeypatch)
    monkeypatch.setattr(mod, "store_cache", lambda prompt, response: None)

    mod.handle_response_message({"prompt": "hi", "response": "hello"})


def test_mark_response_processed_returns_true_once_then_false(isolated_cache, monkeypatch):
    mod = _setup(isolated_cache, monkeypatch)

    assert mod._mark_response_processed("corr-4") is True
    assert mod._mark_response_processed("corr-4") is False
