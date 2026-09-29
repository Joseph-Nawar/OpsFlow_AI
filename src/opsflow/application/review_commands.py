"""Atomic Phase 6 approval, rejection, and retry commands."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import (
    InvalidRejectionReasonError,
    InvalidReviewStateError,
    OrderNotFoundError,
    ReviewPersistenceConflictError,
)
from opsflow.domain import AuditEvent, Order, OrderState, ValidationSeverity
from opsflow.notifications.contracts import NotificationChannel, NotificationKind
from opsflow.notifications.service import create_notification_intent
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_latest_audit_event_id,
    get_latest_review_revision,
    get_order,
    get_order_for_update,
    insert_audit_event,
    update_order_snapshot,
)
from opsflow.review import OperatorContext, ReviewRevision
from opsflow.review.auth import (
    require_approval,
    require_rejection,
    require_retry,
    require_view_access,
)
from opsflow.review.concurrency import compute_review_etag, require_if_match


@dataclass(frozen=True, slots=True)
class ReviewCommandResult:
    """Committed lifecycle state and its fresh review concurrency validator."""

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    etag: str


async def approve_order(
    session: AsyncSession,
    order_id: UUID,
    if_match: str | None,
    operator: OperatorContext,
    recorded_at: datetime,
    review_base_url: str,
) -> ReviewCommandResult:
    """Approve one ready order after rechecking its current authority and ETag."""

    _require_aware_recorded_at(recorded_at)
    require_approval(operator, high_value=False)
    await _require_preflight_etag(session, order_id, if_match)

    try:
        async with session.begin():
            persisted, latest_revision, current_audit_id = await _load_generation(
                session, order_id, locked=True
            )
            require_if_match(if_match, _etag(persisted, latest_revision, current_audit_id))
            if persisted.order.state is not OrderState.READY_FOR_APPROVAL:
                raise InvalidReviewStateError()
            require_approval(
                operator,
                high_value=_has_high_value_warning(persisted),
            )

            final_order = persisted.order.transition_to(OrderState.APPROVED)
            await update_order_snapshot(session, final_order)
            event = AuditEvent(
                id=uuid4(),
                order_id=order_id,
                event_type="ORDER_APPROVED",
                actor=operator.actor,
                occurred_at=recorded_at,
                description="Order approved by operator.",
            )
            await insert_audit_event(session, event)
            await create_notification_intent(
                session,
                order=final_order,
                event=event,
                channel=NotificationChannel.SLACK,
                kind=NotificationKind.ORDER_APPROVED,
                review_base_url=review_base_url,
            )
            if any(
                ("source_system", "GMAIL") in source.metadata
                and isinstance(source.message_id, str)
                and source.message_id.strip()
                for source in persisted.order.source_documents
            ):
                await create_notification_intent(
                    session,
                    order=final_order,
                    event=event,
                    channel=NotificationChannel.GMAIL,
                    kind=NotificationKind.ORDER_APPROVED,
                    review_base_url=review_base_url,
                )
            latest_audit_id = await get_latest_audit_event_id(session, order_id)
    except IntegrityError:
        raise ReviewPersistenceConflictError() from None

    return _command_result(final_order, latest_revision, latest_audit_id)


async def reject_order(
    session: AsyncSession,
    order_id: UUID,
    reason: str,
    if_match: str | None,
    operator: OperatorContext,
    recorded_at: datetime,
) -> ReviewCommandResult:
    """Reject an eligible order with a bounded reason recorded in its audit."""

    _require_aware_recorded_at(recorded_at)
    require_view_access(operator)
    trimmed_reason = _normalize_rejection_reason(reason)
    await _require_preflight_etag(session, order_id, if_match)

    try:
        async with session.begin():
            persisted, latest_revision, current_audit_id = await _load_generation(
                session, order_id, locked=True
            )
            require_if_match(if_match, _etag(persisted, latest_revision, current_audit_id))
            if persisted.order.state not in (
                OrderState.NEEDS_REVIEW,
                OrderState.READY_FOR_APPROVAL,
            ):
                raise InvalidReviewStateError()
            require_rejection(operator, persisted.order.state)

            final_order = persisted.order.transition_to(OrderState.REJECTED)
            await update_order_snapshot(session, final_order)
            event = AuditEvent(
                id=uuid4(),
                order_id=order_id,
                event_type="ORDER_REJECTED",
                actor=operator.actor,
                occurred_at=recorded_at,
                description=f"Order rejected. Reason: {trimmed_reason}",
            )
            await insert_audit_event(session, event)
            latest_audit_id = await get_latest_audit_event_id(session, order_id)
    except IntegrityError:
        raise ReviewPersistenceConflictError() from None

    return _command_result(final_order, latest_revision, latest_audit_id)


async def retry_order(
    session: AsyncSession,
    order_id: UUID,
    if_match: str | None,
    operator: OperatorContext,
    recorded_at: datetime,
) -> ReviewCommandResult:
    """Clear a retryable failure to its persisted origin without resuming work."""

    _require_aware_recorded_at(recorded_at)
    require_retry(operator)
    await _require_preflight_etag(session, order_id, if_match)

    try:
        async with session.begin():
            persisted, latest_revision, current_audit_id = await _load_generation(
                session, order_id, locked=True
            )
            require_if_match(if_match, _etag(persisted, latest_revision, current_audit_id))
            if persisted.order.state is not OrderState.FAILED_RETRYABLE:
                raise InvalidReviewStateError()
            require_retry(operator)

            final_order = persisted.order.retry()
            await update_order_snapshot(session, final_order)
            events = (
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type="ORDER_RETRY_REQUESTED",
                    actor=operator.actor,
                    occurred_at=recorded_at,
                    description="Retry requested by operator.",
                ),
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type="ORDER_RETRY_RESTORED",
                    actor=operator.actor,
                    occurred_at=recorded_at + timedelta(microseconds=1),
                    description=(
                        "Retryable failure cleared; order restored to its recorded failure origin."
                    ),
                ),
            )
            for event in events:
                await insert_audit_event(session, event)
            latest_audit_id = await get_latest_audit_event_id(session, order_id)
    except IntegrityError:
        raise ReviewPersistenceConflictError() from None

    return _command_result(final_order, latest_revision, latest_audit_id)


async def _require_preflight_etag(
    session: AsyncSession,
    order_id: UUID,
    if_match: str | None,
) -> None:
    try:
        persisted, latest_revision, latest_audit_id = await _load_generation(
            session, order_id, locked=False
        )
        require_if_match(if_match, _etag(persisted, latest_revision, latest_audit_id))
    except Exception:
        await session.rollback()
        raise
    await session.rollback()


async def _load_generation(
    session: AsyncSession,
    order_id: UUID,
    *,
    locked: bool,
) -> tuple[PersistedOrder, ReviewRevision | None, UUID | None]:
    persisted = (
        await get_order_for_update(session, order_id)
        if locked
        else await get_order(session, order_id)
    )
    if persisted is None:
        raise OrderNotFoundError(order_id)
    latest_revision = await get_latest_review_revision(session, order_id)
    latest_audit_id = await get_latest_audit_event_id(session, order_id)
    return persisted, latest_revision, latest_audit_id


def _etag(
    persisted: PersistedOrder,
    latest_revision: ReviewRevision | None,
    latest_audit_id: UUID | None,
) -> str:
    order = persisted.order
    return compute_review_etag(
        order.id,
        order.state,
        order.failure_origin,
        latest_revision.revision_number if latest_revision is not None else None,
        latest_revision.id if latest_revision is not None else None,
        latest_audit_id,
    )


def _has_high_value_warning(persisted: PersistedOrder) -> bool:
    return any(
        issue.rule_code == "HIGH_VALUE_APPROVAL_REQUIRED"
        and issue.severity is ValidationSeverity.WARNING
        for issue in persisted.validation_issues
    )


def _normalize_rejection_reason(reason: str) -> str:
    if not isinstance(reason, str):
        raise InvalidRejectionReasonError()
    trimmed = reason.strip()
    if not trimmed or len(trimmed) > 500:
        raise InvalidRejectionReasonError()
    return trimmed


def _command_result(
    order: Order,
    latest_revision: ReviewRevision | None,
    latest_audit_id: UUID | None,
) -> ReviewCommandResult:
    return ReviewCommandResult(
        order_id=order.id,
        state=order.state,
        failure_origin=order.failure_origin,
        etag=compute_review_etag(
            order.id,
            order.state,
            order.failure_origin,
            latest_revision.revision_number if latest_revision is not None else None,
            latest_revision.id if latest_revision is not None else None,
            latest_audit_id,
        ),
    )


def _require_aware_recorded_at(recorded_at: datetime) -> None:
    if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
