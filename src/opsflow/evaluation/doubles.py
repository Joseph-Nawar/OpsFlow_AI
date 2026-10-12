"""Small provider-free doubles used by the M11C application-path runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from opsflow.application.errors import BusinessDataProviderError
from opsflow.extraction.errors import ProviderError, ProviderUnavailableError
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.provider import (
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from opsflow.order_sync.contracts import OrderSyncStep
from opsflow.validation.business_data import BusinessDataProvider
from opsflow.validation.models import BusinessDataLookupRequest, TrustedBusinessData

from .models import (
    CorpusCase,
    ExpectedExtraction,
    LogicalObjectEvidence,
    LogicalObjectIdentity,
    LogicalObjectType,
)


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def scripted_payload(expected: ExpectedExtraction) -> dict[str, Any]:
    """Build provider input from named ground truth for an offline app-path run.

    This payload is only a deterministic input to the existing ``OrderExtractor``.
    The runner never reports the resulting scripted values as model quality.
    """

    return {
        "customer_name": expected.customer_name,
        "customer_reference": expected.customer_reference,
        "po_number": expected.po_number,
        "order_date": _date_text(expected.order_date),
        "requested_delivery_date": _date_text(expected.requested_delivery_date),
        "currency": expected.currency,
        "lines": [
            {
                "sku": line.sku,
                "description": line.description,
                "quantity": _decimal_text(line.quantity),
                "submitted_price": _decimal_text(line.submitted_price),
            }
            for line in expected.lines
        ],
        "notes": expected.notes,
        "evidence": [],
    }


@dataclass(slots=True)
class ProviderObservation:
    """Bounded provider reachability/usage facts for one initial corpus case."""

    calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class RecordingScriptedProvider:
    """Record calls while delegating to the existing ``FakeProvider``."""

    def __init__(
        self,
        case: CorpusCase,
        first_failure: str | None = None,
        repeat_success: bool = False,
    ) -> None:
        outcome: StructuredGenerationResult | ProviderError
        if case.expected_extraction is None:
            outcome = ProviderError("scripted extraction is not available for this case")
        else:
            outcome = StructuredGenerationResult(payload=scripted_payload(case.expected_extraction))
        first_outcome: ProviderError | None = None
        if first_failure == "PROVIDER_UNAVAILABLE":
            first_outcome = ProviderUnavailableError("scripted provider unavailable")
        outcomes: tuple[StructuredGenerationResult | ProviderError, ...]
        if first_outcome is not None:
            outcomes = (first_outcome, outcome)
        else:
            outcomes = (outcome, outcome, outcome) if repeat_success else (outcome,)
        self._provider = FakeProvider(outcomes)
        self.observation = ProviderObservation()

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        self.observation.calls += 1
        result = await self._provider.generate_structured(request)
        self.observation.input_tokens = result.input_tokens
        self.observation.output_tokens = result.output_tokens
        self.observation.total_tokens = result.total_tokens
        return result


class ScriptedProviderFactory:
    """Fresh per-case factory that exposes only bounded call observations."""

    def __init__(self, case: CorpusCase) -> None:
        self.provider = RecordingScriptedProvider(case)

    def __call__(self) -> RecordingScriptedProvider:
        return self.provider


class RecoveryScriptedProviderFactory(ScriptedProviderFactory):
    """Script one bounded retryable extraction failure before normal output."""

    def __init__(self, case: CorpusCase, first_failure: str) -> None:
        self.provider = RecordingScriptedProvider(
            case,
            first_failure=first_failure,
            repeat_success=first_failure != "PROVIDER_UNAVAILABLE",
        )


class FailOnceBusinessDataProvider:
    """Inject one real retryable business-data failure, then delegate normally."""

    def __init__(self, delegate: BusinessDataProvider) -> None:
        self._delegate = delegate
        self._failed = False

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        if not self._failed:
            self._failed = True
            raise BusinessDataProviderError()
        return await self._delegate.get_validation_data(request)


class LogicalObjectTracker:
    """Observe bounded synthetic objects by stable business identity."""

    def __init__(self) -> None:
        self.steps: list[OrderSyncStep] = []
        self._objects: dict[tuple[LogicalObjectType, str], set[str]] = {}

    def record_step(self, step: OrderSyncStep) -> None:
        self.steps.append(step)

    def record_object(
        self,
        object_type: LogicalObjectType,
        stable_business_identity: str,
        object_identity: str,
    ) -> None:
        identities = self._objects.setdefault((object_type, stable_business_identity), set())
        identities.add(object_identity)

    @property
    def identities(self) -> tuple[LogicalObjectIdentity, ...]:
        return tuple(
            LogicalObjectIdentity(
                object_type=object_type,
                stable_business_identity=stable_identity,
                object_identity=object_identity,
            )
            for (object_type, stable_identity), identities in sorted(self._objects.items())
            for object_identity in sorted(identities)
        )

    @property
    def logical_object_count(self) -> int:
        return len(self.identities)

    @property
    def logical_duplication_count(self) -> int:
        return sum(max(0, len(identities) - 1) for identities in self._objects.values())

    def evidence(
        self,
        *,
        original_identities: tuple[LogicalObjectIdentity, ...] = (),
        completed_steps_before_retry: tuple[OrderSyncStep, ...] = (),
        steps_after_retry: tuple[OrderSyncStep, ...] = (),
    ) -> LogicalObjectEvidence:
        resulting_identities = self.identities
        original_duplicate_count = _identity_duplication_count(original_identities)
        replay_created_extra_object = self.logical_duplication_count > original_duplicate_count
        completed_steps = set(completed_steps_before_retry)
        rerun = any(step in completed_steps for step in steps_after_retry)
        return LogicalObjectEvidence(
            executor_reached=bool(self.steps or resulting_identities),
            original_identities=original_identities,
            resulting_identities=resulting_identities,
            original_object_count=len(original_identities),
            resulting_object_count=len(resulting_identities),
            logical_duplication_count=self.logical_duplication_count,
            replay_created_extra_object=replay_created_extra_object,
            completed_step_rerun=rerun,
            completed_steps_before_retry=tuple(step.value for step in completed_steps_before_retry),
            steps_after_retry=tuple(step.value for step in steps_after_retry),
        )


def _identity_duplication_count(identities: tuple[LogicalObjectIdentity, ...]) -> int:
    by_stable_identity: dict[tuple[LogicalObjectType, str], set[str]] = {}
    for identity in identities:
        key = (identity.object_type, identity.stable_business_identity)
        by_stable_identity.setdefault(key, set()).add(identity.object_identity)
    return sum(max(0, len(object_ids) - 1) for object_ids in by_stable_identity.values())


__all__ = [
    "ProviderObservation",
    "FailOnceBusinessDataProvider",
    "LogicalObjectTracker",
    "RecoveryScriptedProviderFactory",
    "RecordingScriptedProvider",
    "ScriptedProviderFactory",
    "scripted_payload",
]
