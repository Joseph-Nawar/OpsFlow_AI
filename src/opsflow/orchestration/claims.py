"""Locked ownership claims for Phase 7 orchestration intake."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import (
    IdempotencyConflictError,
    OrderNotFoundError,
    SourceIdentityMismatchError,
)
from opsflow.documents.common import normalize_mime_type
from opsflow.documents.errors import DocumentValidationError
from opsflow.domain import AuditEvent, OrderState, SourceDocumentType
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_audit_events,
    get_idempotency_record,
    get_order_for_update,
    insert_audit_event,
    update_order_snapshot,
)


class IntakeClaimKind(Enum):
    """Describe the execution ownership granted by one intake claim."""

    INITIAL = "INITIAL"
    RESUME_PROCESSING = "RESUME_PROCESSING"
    RESUME_EXTRACTED = "RESUME_EXTRACTED"
    STAND_DOWN = "STAND_DOWN"


@dataclass(frozen=True, slots=True)
class OrchestrationSourceIdentity:
    """Backend-derived identity for the one source document being claimed."""

    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None


@dataclass(frozen=True, slots=True)
class IntakeClaim:
    """The durable order snapshot and ownership decision from one claim."""

    kind: IntakeClaimKind
    persisted: PersistedOrder
    source_document_id: UUID


async def claim_intake_execution(
    session: AsyncSession,
    *,
    order_id: UUID,
    idempotency_key: str,
    request_fingerprint: str,
    source: OrchestrationSourceIdentity,
    actor: str,
    recorded_at: datetime,
) -> IntakeClaim:
    """Atomically claim one order before any parsing or provider work."""

    if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")

    async with session.begin():
        persisted = await get_order_for_update(session, order_id)
        if persisted is None:
            raise OrderNotFoundError(order_id)

        idempotency = await get_idempotency_record(session, idempotency_key)
        if (
            idempotency is None
            or idempotency.order_id != order_id
            or idempotency.request_fingerprint != request_fingerprint
        ):
            raise IdempotencyConflictError(idempotency_key)

        source_document_id = _require_source_identity(persisted, source, order_id)
        audit_events = await get_audit_events(session, order_id)
        kind = decide_intake_claim_kind(persisted.order.state, audit_events)

        if kind is IntakeClaimKind.INITIAL:
            processing_order = persisted.order.transition_to(OrderState.PROCESSING)
            await update_order_snapshot(session, processing_order)
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type="ORDER_PROCESSING_STARTED",
                    actor=actor,
                    occurred_at=recorded_at,
                    description="Orchestration intake claimed the order for processing.",
                ),
            )
            persisted = PersistedOrder(
                order=processing_order,
                created_at=persisted.created_at,
                validation_issues=persisted.validation_issues,
            )
        elif kind is IntakeClaimKind.RESUME_PROCESSING:
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type="ORDER_PROCESSING_RESUMED",
                    actor=actor,
                    occurred_at=recorded_at,
                    description=(
                        "Human-authorized processing retry redelivery claimed for execution."
                    ),
                ),
            )
        elif kind is IntakeClaimKind.RESUME_EXTRACTED:
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type="ORDER_EXTRACTION_RESUMED",
                    actor=actor,
                    occurred_at=recorded_at,
                    description=(
                        "Human-authorized extraction retry redelivery claimed for execution."
                    ),
                ),
            )

        claim = IntakeClaim(
            kind=kind,
            persisted=persisted,
            source_document_id=source_document_id,
        )

    return claim


def _require_source_identity(
    persisted: PersistedOrder,
    source: OrchestrationSourceIdentity,
    order_id: UUID,
) -> UUID:
    documents = persisted.order.source_documents
    if len(documents) != 1:
        source_document_id = documents[0].id if documents else order_id
        raise SourceIdentityMismatchError(order_id, source_document_id)

    document = documents[0]
    try:
        normalized_mime_type = normalize_mime_type(source.mime_type)
    except DocumentValidationError:
        raise SourceIdentityMismatchError(order_id, document.id) from None
    if (
        document.document_type is not source.document_type
        or document.name != source.name
        or document.mime_type != normalized_mime_type
        or document.sha256 != source.sha256
        or document.message_id != source.message_id
    ):
        raise SourceIdentityMismatchError(order_id, document.id)
    return document.id


_KNOWN_AUDIT_EVENTS = frozenset(
    {
        "ORDER_RECEIVED",
        "ORDER_PROCESSING_STARTED",
        "ORDER_PROCESSING_FAILED",
        "ORDER_PROCESSING_RESUMED",
        "ORDER_EXTRACTION_COMPLETED",
        "ORDER_EXTRACTION_RESUMED",
        "ORDER_VALIDATION_FAILED",
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
        "ORDER_APPROVED",
        "ORDER_REJECTED",
    }
)


def decide_intake_claim_kind(
    state: OrderState,
    audit_events: tuple[AuditEvent, ...],
) -> IntakeClaimKind:
    """Decide ownership from one locked state and deterministic audit history."""

    if not isinstance(state, OrderState) or not isinstance(audit_events, tuple):
        return IntakeClaimKind.STAND_DOWN

    ordered = tuple(sorted(audit_events, key=lambda event: (event.occurred_at, event.id)))
    if any(
        not isinstance(event, AuditEvent) or event.event_type not in _KNOWN_AUDIT_EVENTS
        for event in ordered
    ):
        return IntakeClaimKind.STAND_DOWN
    if ordered and len({event.order_id for event in ordered}) != 1:
        return IntakeClaimKind.STAND_DOWN

    event_types = tuple(event.event_type for event in ordered)
    if state is OrderState.RECEIVED:
        if event_types == ("ORDER_RECEIVED",):
            return IntakeClaimKind.INITIAL
        return IntakeClaimKind.STAND_DOWN

    valid, phase, processing_retry, extracted_retry = _audit_history_status(event_types)
    if not valid:
        return IntakeClaimKind.STAND_DOWN
    if state is OrderState.PROCESSING:
        if phase not in {"PROCESSING", "PROCESSING_RESTORED"}:
            return IntakeClaimKind.STAND_DOWN
        if processing_retry:
            return IntakeClaimKind.RESUME_PROCESSING
        return IntakeClaimKind.STAND_DOWN

    if state is OrderState.EXTRACTED:
        if phase not in {"EXTRACTED", "EXTRACTED_FAILED", "EXTRACTED_RESTORED"}:
            return IntakeClaimKind.STAND_DOWN
        if extracted_retry:
            return IntakeClaimKind.RESUME_EXTRACTED
        return IntakeClaimKind.STAND_DOWN

    return IntakeClaimKind.STAND_DOWN


def _audit_history_status(
    event_types: tuple[str, ...],
) -> tuple[bool, str, bool, bool]:
    """Parse lifecycle history and report the latest unconsumed retry origins."""

    if event_types[:2] != ("ORDER_RECEIVED", "ORDER_PROCESSING_STARTED"):
        return False, "RECEIVED", False, False

    generations: dict[str, list[bool]] = {"PROCESSING": [], "EXTRACTED": []}
    phase = "RECEIVED"
    pending_failure_origin: str | None = None
    pending_request_origin: str | None = None
    received_seen = False
    processing_started = False
    extraction_completed = False

    for index, event_type in enumerate(event_types):
        if event_type == "ORDER_RECEIVED":
            if received_seen or index != 0:
                return False, phase, False, False
            received_seen = True
        elif event_type == "ORDER_PROCESSING_STARTED":
            if (
                processing_started
                or extraction_completed
                or phase not in {"RECEIVED", "PROCESSING"}
            ):
                return False, phase, False, False
            processing_started = True
            phase = "PROCESSING"
        elif event_type == "ORDER_PROCESSING_FAILED":
            if not processing_started or phase != "PROCESSING":
                return False, phase, False, False
            pending_failure_origin = "PROCESSING"
            phase = "PROCESSING_FAILED"
        elif event_type == "ORDER_EXTRACTION_COMPLETED":
            if extraction_completed or pending_failure_origin or pending_request_origin:
                return False, phase, False, False
            if processing_started and phase != "PROCESSING":
                return False, phase, False, False
            extraction_completed = True
            phase = "EXTRACTED"
        elif event_type == "ORDER_VALIDATION_FAILED":
            if pending_failure_origin or pending_request_origin:
                return False, phase, False, False
            if processing_started and not extraction_completed:
                return False, phase, False, False
            pending_failure_origin = "EXTRACTED"
            phase = "EXTRACTED_FAILED"
        elif event_type == "ORDER_RETRY_REQUESTED":
            if pending_failure_origin is None or pending_request_origin is not None:
                return False, phase, False, False
            pending_request_origin = pending_failure_origin
        elif event_type == "ORDER_RETRY_RESTORED":
            if pending_request_origin is None:
                return False, phase, False, False
            generations[pending_request_origin].append(False)
            phase = (
                "PROCESSING_RESTORED"
                if pending_request_origin == "PROCESSING"
                else "EXTRACTED_RESTORED"
            )
            pending_failure_origin = None
            pending_request_origin = None
        elif event_type == "ORDER_PROCESSING_RESUMED":
            if phase != "PROCESSING_RESTORED" or not _consume_latest_generation(
                generations["PROCESSING"]
            ):
                return False, phase, False, False
            phase = "PROCESSING"
        elif event_type == "ORDER_EXTRACTION_RESUMED":
            if phase != "EXTRACTED_RESTORED" or not _consume_latest_generation(
                generations["EXTRACTED"]
            ):
                return False, phase, False, False
            phase = "EXTRACTED"
        elif event_type in {"ORDER_APPROVED", "ORDER_REJECTED"}:
            return False, phase, False, False

    if pending_failure_origin is not None or pending_request_origin is not None:
        return False, phase, False, False
    return (
        True,
        phase,
        bool(generations["PROCESSING"] and not generations["PROCESSING"][-1]),
        bool(generations["EXTRACTED"] and not generations["EXTRACTED"][-1]),
    )


def _consume_latest_generation(generations: list[bool]) -> bool:
    for index in range(len(generations) - 1, -1, -1):
        if not generations[index]:
            generations[index] = True
            return True
    return False
