"""Durable notification intent, claim, and outcome application services."""

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import AuditEvent, Order, ValidationIssue
from opsflow.notifications.contracts import (
    NotificationChannel,
    NotificationClaim,
    NotificationDelivery,
    NotificationKind,
    NotificationOutcome,
    NotificationOutcomeKind,
    NotificationOutcomeResult,
    NotificationStatus,
)
from opsflow.notifications.payloads import render_gmail_approval_payload, render_slack_payload
from opsflow.persistence.mappers import notification_delivery_from_model
from opsflow.persistence.notification_repository import (
    claim_one_eligible_notification,
    finalize_expired_last_attempts,
    get_notification_delivery_for_update,
    insert_notification_delivery,
)


class NotificationNotFoundError(Exception):
    """The requested persisted notification does not exist."""


class StaleNotificationClaimError(Exception):
    """The supplied claim token is no longer the active delivery generation."""


async def create_notification_intent(
    session: AsyncSession,
    *,
    order: Order,
    event: AuditEvent,
    channel: NotificationChannel,
    kind: NotificationKind,
    review_base_url: str,
    issues: Sequence[ValidationIssue] = (),
) -> None:
    """Insert a rendered intent inside the caller's business transaction."""

    if event.order_id != order.id:
        raise ValueError("notification event must belong to its order")
    if channel is NotificationChannel.SLACK:
        payload = render_slack_payload(kind, order, issues, review_base_url)
    elif channel is NotificationChannel.GMAIL and kind is NotificationKind.ORDER_APPROVED:
        message_id = _gmail_message_id(order)
        payload = render_gmail_approval_payload(order, message_id)
    else:
        raise ValueError("notification channel and kind are not supported together")

    delivery = NotificationDelivery(
        id=uuid4(),
        order_id=order.id,
        trigger_audit_event_id=event.id,
        channel=channel,
        kind=kind,
        payload=payload,
        status=NotificationStatus.PENDING,
        attempt_count=0,
        claim_token=None,
        claim_expires_at=None,
        next_attempt_at=event.occurred_at,
        provider_reference=None,
        last_failure_code=None,
        created_at=event.occurred_at,
        updated_at=event.occurred_at,
    )
    await insert_notification_delivery(session, delivery)


async def claim_next_notification(session: AsyncSession) -> NotificationClaim | None:
    """Commit and return one new five-minute notification claim, if available."""

    async with session.begin():
        await finalize_expired_last_attempts(session)
        row = await claim_one_eligible_notification(session)
        if row is None:
            return None

        claim_token = uuid4()
        row.status = NotificationStatus.CLAIMED.value
        row.attempt_count += 1
        row.claim_token = claim_token
        row.claim_expires_at = func.now() + text("interval '5 minutes'")
        row.updated_at = func.now()
        await session.flush()
        await session.refresh(row)
        delivery = notification_delivery_from_model(row)
        assert delivery.claim_expires_at is not None
        return NotificationClaim(
            notification_id=delivery.id,
            channel=delivery.channel,
            kind=delivery.kind,
            payload=delivery.payload,
            attempt_number=delivery.attempt_count,
            claim_token=claim_token,
            claim_expires_at=delivery.claim_expires_at,
        )


async def record_notification_outcome(
    session: AsyncSession,
    notification_id: UUID,
    outcome: NotificationOutcome,
) -> NotificationOutcomeResult:
    """Persist a bounded provider outcome for the current unexpired claim only."""

    async with session.begin():
        row = await get_notification_delivery_for_update(session, notification_id)
        if row is None:
            raise NotificationNotFoundError
        database_now = await session.scalar(select(func.now()))
        if (
            row.status != NotificationStatus.CLAIMED.value
            or row.claim_token != outcome.claim_token
            or row.claim_expires_at is None
            or database_now is None
            or row.claim_expires_at <= database_now
        ):
            raise StaleNotificationClaimError

        row.claim_token = None
        row.claim_expires_at = None
        row.updated_at = func.now()
        if outcome.kind is NotificationOutcomeKind.DELIVERED:
            row.status = NotificationStatus.DELIVERED.value
            row.provider_reference = outcome.provider_reference
            row.last_failure_code = None
        else:
            assert outcome.failure_code is not None
            row.provider_reference = None
            row.last_failure_code = outcome.failure_code.value
            if row.attempt_count >= 3:
                row.status = NotificationStatus.FAILED_FINAL.value
            else:
                row.status = NotificationStatus.PENDING.value
                retry_delay = _retry_delay_seconds(
                    row.attempt_count,
                    slack=row.channel == NotificationChannel.SLACK.value,
                    retry_after_seconds=outcome.retry_after_seconds,
                )
                row.next_attempt_at = func.now() + timedelta(seconds=retry_delay)

        await session.flush()
        await session.refresh(row)
        delivery = notification_delivery_from_model(row)
        return NotificationOutcomeResult(
            notification_id=delivery.id,
            status=delivery.status,
            attempt_count=delivery.attempt_count,
            next_attempt_at=delivery.next_attempt_at,
            provider_reference=delivery.provider_reference,
            last_failure_code=delivery.last_failure_code,
        )


def _retry_delay_seconds(
    attempt_count: int,
    *,
    slack: bool,
    retry_after_seconds: int | None,
) -> int:
    """Choose the bounded backend retry delay after a non-final attempt."""

    if attempt_count == 1:
        base_delay = 30
    elif attempt_count == 2:
        base_delay = 120
    else:
        raise ValueError("only retryable notification attempts have a retry delay")
    if not slack or retry_after_seconds is None:
        return base_delay
    if type(retry_after_seconds) is not int or not 0 <= retry_after_seconds <= 300:
        raise ValueError("retry_after_seconds must be an integer from 0 through 300")
    return max(base_delay, min(retry_after_seconds, 300))


def _gmail_message_id(order: Order) -> str:
    for source in order.source_documents:
        if ("source_system", "GMAIL") in source.metadata:
            if isinstance(source.message_id, str) and source.message_id.strip():
                return source.message_id
            break
    raise ValueError("Gmail approval notification requires persisted Gmail provenance")
