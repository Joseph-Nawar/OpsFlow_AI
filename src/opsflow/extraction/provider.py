"""Provider-neutral asynchronous structured-generation boundary."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StructuredGenerationRequest:
    """Portable input required for one structured extraction request."""

    prompt_version: str
    system_instruction: str
    user_content: str
    response_schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StructuredGenerationResult:
    """Provider-neutral structured payload returned by one generation call."""

    payload: object
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")


class LLMProvider(Protocol):
    """Minimal asynchronous interface for structured generation."""

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult: ...


__all__ = [
    "LLMProvider",
    "StructuredGenerationRequest",
    "StructuredGenerationResult",
]
