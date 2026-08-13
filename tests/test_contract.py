from app.main import PromptResponse


def test_prompt_response_field_names_are_stable():
    assert set(PromptResponse.model_fields) == {
        "response",
        "cached",
        "similarity",
        "latency_ms",
        "status",
        "job_id",
        "cache_reason",
    }


def test_prompt_response_field_types_and_defaults_are_stable():
    fields = PromptResponse.model_fields

    assert fields["response"].annotation == str | None
    assert fields["response"].default is None

    assert fields["cached"].annotation is bool
    assert fields["cached"].is_required()

    assert fields["similarity"].annotation == float | None
    assert fields["similarity"].default is None

    assert fields["latency_ms"].annotation == float | None
    assert fields["latency_ms"].default is None

    assert fields["status"].annotation is str
    assert fields["status"].default == "done"

    assert fields["job_id"].annotation == str | None
    assert fields["job_id"].default is None

    assert fields["cache_reason"].annotation == str | None
    assert fields["cache_reason"].default is None


def test_prompt_response_serializes_only_known_fields_for_a_cache_hit():
    body = PromptResponse(response="answer", cached=True, similarity=0.91, latency_ms=1.2, cache_reason="hit")

    assert body.model_dump() == {
        "response": "answer",
        "cached": True,
        "similarity": 0.91,
        "latency_ms": 1.2,
        "status": "done",
        "job_id": None,
        "cache_reason": "hit",
    }


def test_prompt_response_requires_cached_field():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PromptResponse()
