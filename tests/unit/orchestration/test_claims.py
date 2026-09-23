"""Pure claim-generation and immutable contract tests for Phase 7 intake."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from opsflow.domain import AuditEvent, Order, OrderState, SourceDocumentType
from opsflow.orchestration.claims import (
    IntakeClaim,
    IntakeClaimKind,
    OrchestrationSourceIdentity,
    decide_intake_claim_kind,
)
from opsflow.persistence.repositories import PersistedOrder

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
BASE_TIME = datetime(2030, 1, 1, tzinfo=UTC)


def _event(event_type: str, position: int, *, occurred_at: datetime | None = None) -> AuditEvent:
    return AuditEvent(
        id=UUID(int=position),
        order_id=ORDER_ID,
        event_type=event_type,
        actor="reviewer:test",
        occurred_at=occurred_at or BASE_TIME + timedelta(seconds=position),
        description=f"synthetic {event_type}",
    )


def _events(*event_types: str) -> tuple[AuditEvent, ...]:
    return tuple(_event(event_type, position) for position, event_type in enumerate(event_types, 1))


def test_intake_claim_kind_has_exact_values() -> None:
    assert IntakeClaimKind.INITIAL.value == "INITIAL"
    assert IntakeClaimKind.RESUME_PROCESSING.value == "RESUME_PROCESSING"
    assert IntakeClaimKind.RESUME_EXTRACTED.value == "RESUME_EXTRACTED"
    assert IntakeClaimKind.STAND_DOWN.value == "STAND_DOWN"


def test_claim_records_are_frozen_and_slotted() -> None:
    persisted = PersistedOrder(
        order=Order.received(ORDER_ID),
        created_at=BASE_TIME,
        validation_issues=(),
    )
    source = OrchestrationSourceIdentity(
        document_type=SourceDocumentType.PDF,
        name="invoice.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        message_id="message-1",
    )
    claim = IntakeClaim(
        kind=IntakeClaimKind.INITIAL,
        persisted=persisted,
        source_document_id=uuid4(),
    )

    for record, field, value in (
        (source, "name", "other.pdf"),
        (claim, "kind", IntakeClaimKind.STAND_DOWN),
    ):
        assert not hasattr(record, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(record, field, value)


@pytest.mark.parametrize(
    ("state", "event_types", "expected"),
    [
        (
            OrderState.RECEIVED,
            ("ORDER_RECEIVED",),
            IntakeClaimKind.INITIAL,
        ),
        (
            OrderState.PROCESSING,
            ("ORDER_RECEIVED", "ORDER_PROCESSING_STARTED"),
            IntakeClaimKind.STAND_DOWN,
        ),
        (
            OrderState.PROCESSING,
            (
                "ORDER_PROCESSING_STARTED",
                "ORDER_PROCESSING_FAILED",
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
            ),
            IntakeClaimKind.RESUME_PROCESSING,
        ),
        (
            OrderState.PROCESSING,
            (
                "ORDER_PROCESSING_STARTED",
                "ORDER_PROCESSING_FAILED",
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
                "ORDER_PROCESSING_RESUMED",
            ),
            IntakeClaimKind.STAND_DOWN,
        ),
        (
            OrderState.PROCESSING,
            (
                "ORDER_PROCESSING_STARTED",
                "ORDER_PROCESSING_FAILED",
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
                "ORDER_PROCESSING_RESUMED",
                "ORDER_PROCESSING_FAILED",
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
            ),
            IntakeClaimKind.RESUME_PROCESSING,
        ),
        (
            OrderState.EXTRACTED,
            ("ORDER_EXTRACTION_COMPLETED",),
            IntakeClaimKind.STAND_DOWN,
        ),
        (
            OrderState.EXTRACTED,
            (
                "ORDER_EXTRACTION_COMPLETED",
                "ORDER_VALIDATION_FAILED",
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
            ),
            IntakeClaimKind.RESUME_EXTRACTED,
        ),
        (
            OrderState.EXTRACTED,
            (
                "ORDER_EXTRACTION_COMPLETED",
                "ORDER_VALIDATION_FAILED",
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
                "ORDER_EXTRACTION_RESUMED",
            ),
            IntakeClaimKind.STAND_DOWN,
        ),
        (
            OrderState.SYNCING,
            (
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
            ),
            IntakeClaimKind.STAND_DOWN,
        ),
        (
            OrderState.FAILED_RETRYABLE,
            ("ORDER_PROCESSING_FAILED",),
            IntakeClaimKind.STAND_DOWN,
        ),
        (
            OrderState.NEEDS_REVIEW,
            ("ORDER_VALIDATION_FAILED",),
            IntakeClaimKind.STAND_DOWN,
        ),
        (
            OrderState.COMPLETED,
            ("ORDER_APPROVED",),
            IntakeClaimKind.STAND_DOWN,
        ),
    ],
)
def test_claim_decision_covers_lifecycle_and_retry_generations(
    state: OrderState,
    event_types: tuple[str, ...],
    expected: IntakeClaimKind,
) -> None:
    assert decide_intake_claim_kind(state, _events(*event_types)) is expected


def test_unrecognized_or_impossible_processing_sequence_stands_down() -> None:
    assert (
        decide_intake_claim_kind(
            OrderState.PROCESSING,
            _events("ORDER_PROCESSING_STARTED", "UNRECOGNIZED_EVENT"),
        )
        is IntakeClaimKind.STAND_DOWN
    )
    assert (
        decide_intake_claim_kind(
            OrderState.PROCESSING,
            _events("ORDER_RETRY_RESTORED"),
        )
        is IntakeClaimKind.STAND_DOWN
    )


def test_audit_ties_are_ordered_by_occurred_at_then_id() -> None:
    tied_at = BASE_TIME + timedelta(minutes=1)
    events = (
        _event("ORDER_RETRY_RESTORED", 5, occurred_at=tied_at),
        _event("ORDER_PROCESSING_STARTED", 1),
        _event("ORDER_PROCESSING_FAILED", 2),
        _event("ORDER_RETRY_REQUESTED", 3),
        _event("ORDER_PROCESSING_RESUMED", 4, occurred_at=tied_at),
    )

    assert decide_intake_claim_kind(OrderState.PROCESSING, events) is IntakeClaimKind.STAND_DOWN


def test_later_extracted_retry_is_not_invalidated_by_consumed_processing_retry() -> None:
    events = _events(
        "ORDER_RECEIVED",
        "ORDER_PROCESSING_STARTED",
        "ORDER_PROCESSING_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
        "ORDER_PROCESSING_RESUMED",
        "ORDER_EXTRACTION_COMPLETED",
        "ORDER_VALIDATION_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
    )

    assert (
        decide_intake_claim_kind(OrderState.EXTRACTED, events) is IntakeClaimKind.RESUME_EXTRACTED
    )


def test_extracted_retry_resume_consumes_the_latest_extracted_generation() -> None:
    events = _events(
        "ORDER_RECEIVED",
        "ORDER_PROCESSING_STARTED",
        "ORDER_PROCESSING_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
        "ORDER_PROCESSING_RESUMED",
        "ORDER_EXTRACTION_COMPLETED",
        "ORDER_VALIDATION_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
        "ORDER_EXTRACTION_RESUMED",
    )

    assert decide_intake_claim_kind(OrderState.EXTRACTED, events) is IntakeClaimKind.STAND_DOWN


def test_later_extracted_retry_generation_can_resume_after_an_earlier_one_is_consumed() -> None:
    events = _events(
        "ORDER_RECEIVED",
        "ORDER_PROCESSING_STARTED",
        "ORDER_PROCESSING_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
        "ORDER_PROCESSING_RESUMED",
        "ORDER_EXTRACTION_COMPLETED",
        "ORDER_VALIDATION_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
        "ORDER_EXTRACTION_RESUMED",
        "ORDER_VALIDATION_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
    )

    assert (
        decide_intake_claim_kind(OrderState.EXTRACTED, events) is IntakeClaimKind.RESUME_EXTRACTED
    )


@pytest.mark.parametrize("impossible_event", ["ORDER_APPROVED", "ORDER_REJECTED"])
def test_impossible_processing_history_stands_down(
    impossible_event: str,
) -> None:
    events = _events(
        "ORDER_RECEIVED",
        "ORDER_PROCESSING_STARTED",
        "ORDER_PROCESSING_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
        impossible_event,
    )

    assert decide_intake_claim_kind(OrderState.PROCESSING, events) is IntakeClaimKind.STAND_DOWN
