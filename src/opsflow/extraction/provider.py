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
