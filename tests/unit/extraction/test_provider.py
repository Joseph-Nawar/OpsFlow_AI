import inspect
from dataclasses import FrozenInstanceError, fields

import pytest

from opsflow.extraction.provider import (
    LLMProvider,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)


def test_request_and_result_are_frozen_slotted_provider_neutral_records() -> None:
    request = StructuredGenerationRequest(
        prompt_version="phase4-extraction-v1",
        system_instruction="extract only",
        user_content="text:body",
        response_schema={"type": "object"},
    )
    result = StructuredGenerationResult(payload={"customer_name": None})

    assert request.response_schema == {"type": "object"}
    assert result.payload == {"customer_name": None}
    assert request.__class__.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
    assert result.__class__.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
    assert not hasattr(request, "__dict__")
    assert not hasattr(result, "__dict__")
    assert [field.name for field in fields(request)] == [
        "prompt_version",
        "system_instruction",
        "user_content",
        "response_schema",
    ]
    assert [field.name for field in fields(result)] == ["payload"]

    with pytest.raises(FrozenInstanceError):
        request.prompt_version = "changed"  # type: ignore[misc]


def test_provider_protocol_exposes_only_async_structured_generation() -> None:
    assert inspect.iscoroutinefunction(LLMProvider.generate_structured)
    declared_methods = [
        name
        for name, value in vars(LLMProvider).items()
        if callable(value) and not name.startswith("__")
    ]
    assert declared_methods == ["generate_structured"]
