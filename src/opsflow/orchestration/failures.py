"""Typed operational failure classification for Phase 7 orchestration."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
    OrderNotFoundError,
    ValidationFactsChangedError,
)
from opsflow.documents.errors import DocumentProcessingError
from opsflow.domain import AuditEvent, InvalidStateTransitionError, OrderState
from opsflow.extraction.errors import (
    ExtractionResponseError,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_order_for_update,
    insert_audit_event,
    update_order_snapshot,
)


class FailureDisposition(Enum):
    RETRYABLE = "RETRYABLE"
    FINAL = "FINAL"


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """The fixed lifecycle and audit outcome for one operational failure."""

    disposition: FailureDisposition
    origin: OrderState
    target: OrderState
    event_type: str
    description: str


_PROCESSING_EVENT = "ORDER_PROCESSING_FAILED"
_PROCESSING_DESCRIPTION = "Orchestration processing stopped with a persisted operational failure."
_EXTRACTED_EVENT = "ORDER_VALIDATION_FAILED"
_EXTRACTED_DESCRIPTION = (
    "Deterministic validation could not complete; a persisted operational failure was recorded."
)


def _classification(
    disposition: FailureDisposition,
    origin: OrderState,
    event_type: str,
    description: str,
) -> FailureClassification:
    target = (
        OrderState.FAILED_RETRYABLE
        if disposition is FailureDisposition.RETRYABLE
        else OrderState.FAILED_FINAL
    )
    return FailureClassification(disposition, origin, target, event_type, description)


def classify_processing_failure(error: BaseException) -> FailureClassification:
    """Map one processing exception by type to a fixed safe classification."""

    if isinstance(error, (ProviderTimeoutError, ProviderUnavailableError)):
        disposition = FailureDisposition.RETRYABLE
    elif isinstance(error, (ExtractionResponseError, ProviderError, DocumentProcessingError)):
        disposition = FailureDisposition.FINAL
    else:
        disposition = FailureDisposition.FINAL
    return _classification(
        disposition,
        OrderState.PROCESSING,
        _PROCESSING_EVENT,
        _PROCESSING_DESCRIPTION,
    )


def classify_extracted_failure(error: BaseException) -> FailureClassification:
    """Map one extracted-stage exception by type to a fixed safe classification."""

    if isinstance(error, (BusinessDataProviderError, ValidationFactsChangedError)):
        disposition = FailureDisposition.RETRYABLE
    elif isinstance(error, InvalidTrustedDataError):
        disposition = FailureDisposition.FINAL
    else:
        disposition = FailureDisposition.FINAL
    return _classification(
        disposition,
        OrderState.EXTRACTED,
        _EXTRACTED_EVENT,
        _EXTRACTED_DESCRIPTION,
    )


def _require_aware_recorded_at(recorded_at: datetime) -> None:
    if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")


def _require_valid_classification(classification: FailureClassification) -> None:
    if classification.origin is OrderState.PROCESSING:
        expected_event = _PROCESSING_EVENT
        expected_description = _PROCESSING_DESCRIPTION
    elif classification.origin is OrderState.EXTRACTED:
        expected_event = _EXTRACTED_EVENT
        expected_description = _EXTRACTED_DESCRIPTION
    else:
        raise ValueError("failure classification origin is not orchestration-owned")

    expected_target = (
        OrderState.FAILED_RETRYABLE
        if classification.disposition is FailureDisposition.RETRYABLE
        else OrderState.FAILED_FINAL
        if classification.disposition is FailureDisposition.FINAL
        else None
    )
    if (
        expected_target is None
        or classification.target is not expected_target
        or classification.event_type != expected_event
        or classification.description != expected_description
    ):
        raise ValueError("failure classification is inconsistent")


async def persist_orchestration_failure(
    session: AsyncSession,
    *,
    order_id: UUID,
    classification: FailureClassification,
    actor: str,
    recorded_at: datetime,
) -> PersistedOrder:
    """Persist one typed failure and its audit event in one short transaction."""

    _require_aware_recorded_at(recorded_at)
    _require_valid_classification(classification)

    async with session.begin():
        locked = await get_order_for_update(session, order_id)
        if locked is None:
            raise OrderNotFoundError(order_id)
        if locked.order.state is not classification.origin:
            raise InvalidStateTransitionError(
                locked.order.state,
                classification.target,
                "persist_orchestration_failure",
            )

        failed_order = locked.order.transition_to(classification.target)
        await update_order_snapshot(session, failed_order)
        await insert_audit_event(
            session,
            AuditEvent(
                id=uuid4(),
                order_id=order_id,
                event_type=classification.event_type,
                actor=actor,
                occurred_at=recorded_at,
                description=classification.description,
            ),
        )

    return PersistedOrder(failed_order, locked.created_at, locked.validation_issues)


__all__ = [
    "FailureClassification",
    "FailureDisposition",
    "classify_extracted_failure",
    "classify_processing_failure",
    "persist_orchestration_failure",
]
