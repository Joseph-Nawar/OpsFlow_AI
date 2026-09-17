"""Deterministic, network-free provider for tests and local development."""

from collections import deque
from collections.abc import Iterable

from opsflow.extraction.errors import ProviderError
from opsflow.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResult,
)

type FakeOutcome = StructuredGenerationResult | ProviderError


class FakeProvider:
    """Return or raise scripted outcomes without inspecting the request payload."""

    def __init__(self, outcomes: Iterable[FakeOutcome]) -> None:
        self._outcomes = deque(outcomes)
        self.requests: list[StructuredGenerationRequest] = []

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        self.requests.append(request)
        if not self._outcomes:
            raise ProviderError("script exhausted")

        outcome = self._outcomes.popleft()
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome


__all__ = ["FakeOutcome", "FakeProvider"]
