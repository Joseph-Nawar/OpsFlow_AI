"""Locked ownership claims for Phase 7 orchestration intake."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from math import ceil
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import (
    IdempotencyConflictError,
    OrderNotFoundError,
    SourceIdentityMismatchError,
)
from opsflow.documents.common import normalize_mime_type
from opsflow.documents.errors import DocumentValidationError
from opsflow.domain import AuditEvent, OrderState, SourceDocumentType
from opsflow.orchestration.ownership import INTAKE_OWNERSHIP_LEASE_SECONDS
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_audit_events,
    get_idempotency_record,
    get_order_for_update,
    insert_audit_event,
    set_intake_ownership,
    update_order_snapshot,
)


class IntakeClaimKind(Enum):
    """Describe the execution ownership granted by one intake claim."""

    INITIAL = "INITIAL"
    RESUME_PROCESSING = "RESUME_PROCESSING"
    RESUME_EXTRACTED = "RESUME_EXTRACTED"
    RECOVER_PROCESSING = "RECOVER_PROCESSING"
    RECOVER_EXTRACTED = "RECOVER_EXTRACTED"
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
    ownership_token: UUID | None = None
    ownership_expires_at: datetime | None = None
    retry_after_seconds: int | None = None


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
        retry_after_seconds: int | None = None
        if kind is IntakeClaimKind.STAND_DOWN:
            kind, retry_after_seconds = await _recover_stale_ownership(
                session,
                persisted,
                audit_events,
            )

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
                intake_claim_token=persisted.intake_claim_token,
                intake_claim_expires_at=persisted.intake_claim_expires_at,
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
        elif kind in {
            IntakeClaimKind.RECOVER_PROCESSING,
            IntakeClaimKind.RECOVER_EXTRACTED,
        }:
            recovered_event_type = (
                "ORDER_PROCESSING_RECOVERED"
                if kind is IntakeClaimKind.RECOVER_PROCESSING
                else "ORDER_EXTRACTION_RECOVERED"
            )
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type=recovered_event_type,
                    actor=actor,
                    occurred_at=recorded_at,
                    description=(
                        "Stale orchestration intake ownership was recovered for the existing "
                        "order and source."
                    ),
                ),
            )

        if kind in {
            IntakeClaimKind.INITIAL,
            IntakeClaimKind.RESUME_PROCESSING,
            IntakeClaimKind.RESUME_EXTRACTED,
            IntakeClaimKind.RECOVER_PROCESSING,
            IntakeClaimKind.RECOVER_EXTRACTED,
        }:
            ownership_token = uuid4()
            ownership_expires_at = await set_intake_ownership(
                session,
                order_id,
                ownership_token,
                INTAKE_OWNERSHIP_LEASE_SECONDS,
            )
            persisted = replace(
                persisted,
                intake_claim_token=ownership_token,
                intake_claim_expires_at=ownership_expires_at,
            )

        claim = IntakeClaim(
            kind=kind,
            persisted=persisted,
            source_document_id=source_document_id,
            ownership_token=(
                persisted.intake_claim_token if kind is not IntakeClaimKind.STAND_DOWN else None
            ),
            ownership_expires_at=(
                persisted.intake_claim_expires_at
                if kind is not IntakeClaimKind.STAND_DOWN
                else None
            ),
            retry_after_seconds=retry_after_seconds,
        )

    return claim


async def _recover_stale_ownership(
    session: AsyncSession,
    persisted: PersistedOrder,
    audit_events: tuple[AuditEvent, ...],
) -> tuple[IntakeClaimKind, int | None]:
    """Choose recovery or a safe delay from one post-lock database-clock read."""

    if (
        not _is_recoverable_in_progress_history(persisted.order.state, audit_events)
        or persisted.intake_claim_token is None
        or persisted.intake_claim_expires_at is None
        or persisted.order.state not in {OrderState.PROCESSING, OrderState.EXTRACTED}
    ):
        return IntakeClaimKind.STAND_DOWN, None

    now = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(now, datetime):
        return IntakeClaimKind.STAND_DOWN, None
    if persisted.intake_claim_expires_at <= now:
        return (
            (
                IntakeClaimKind.RECOVER_PROCESSING
                if persisted.order.state is OrderState.PROCESSING
                else IntakeClaimKind.RECOVER_EXTRACTED
            ),
            None,
        )
    remaining = ceil((persisted.intake_claim_expires_at - now).total_seconds())
    return IntakeClaimKind.STAND_DOWN, max(1, min(remaining, INTAKE_OWNERSHIP_LEASE_SECONDS))


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
        "ORDER_PROCESSING_RECOVERED",
        "ORDER_PROCESSING_FAILED",
        "ORDER_PROCESSING_RESUMED",
        "ORDER_EXTRACTION_COMPLETED",
        "ORDER_EXTRACTION_RECOVERED",
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

    if not isinstance(state, OrderState):
        return IntakeClaimKind.STAND_DOWN

    event_types = _normalized_audit_event_types(audit_events)
    if event_types is None:
        return IntakeClaimKind.STAND_DOWN

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


def _normalized_audit_event_types(
    audit_events: tuple[AuditEvent, ...],
) -> tuple[str, ...] | None:
    if not isinstance(audit_events, tuple) or any(
        not isinstance(event, AuditEvent) or event.event_type not in _KNOWN_AUDIT_EVENTS
        for event in audit_events
    ):
        return None
    ordered = tuple(sorted(audit_events, key=lambda event: (event.occurred_at, event.id)))
    if ordered and len({event.order_id for event in ordered}) != 1:
        return None
    return tuple(event.event_type for event in ordered)


def _is_recoverable_in_progress_history(
    state: OrderState,
    audit_events: tuple[AuditEvent, ...],
) -> bool:
    event_types = _normalized_audit_event_types(audit_events)
    if event_types is None:
        return False
    valid, phase, _, _ = _audit_history_status(event_types)
    if not valid:
        return False
    if state is OrderState.PROCESSING:
        return phase in {"PROCESSING", "PROCESSING_RESTORED"}
    if state is OrderState.EXTRACTED:
        return phase in {"EXTRACTED", "EXTRACTED_FAILED", "EXTRACTED_RESTORED"}
    return False


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
        elif event_type == "ORDER_PROCESSING_RECOVERED":
            if pending_failure_origin or pending_request_origin or phase != "PROCESSING":
                return False, phase, False, False
            phase = "PROCESSING"
        elif event_type == "ORDER_EXTRACTION_COMPLETED":
            if extraction_completed or pending_failure_origin or pending_request_origin:
                return False, phase, False, False
            if processing_started and phase != "PROCESSING":
                return False, phase, False, False
            extraction_completed = True
            phase = "EXTRACTED"
        elif event_type == "ORDER_EXTRACTION_RECOVERED":
            if pending_failure_origin or pending_request_origin or phase != "EXTRACTED":
                return False, phase, False, False
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
