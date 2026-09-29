"""Transaction-neutral persistence operations for notification delivery rows."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.notifications.contracts import NotificationDelivery, NotificationStatus
from opsflow.persistence.mappers import notification_delivery_to_model
from opsflow.persistence.models import NotificationDeliveryModel


async def insert_notification_delivery(
    session: AsyncSession, delivery: NotificationDelivery
) -> None:
    """Append one immutable intent and flush it inside the caller's transaction."""

    session.add(notification_delivery_to_model(delivery))
    await session.flush()


async def finalize_expired_last_attempts(session: AsyncSession) -> int:
    """Fail exhausted expired leases without granting another provider attempt."""

    result = cast(
        CursorResult[Any],
        await session.execute(
            update(NotificationDeliveryModel)
            .where(
                NotificationDeliveryModel.status == NotificationStatus.CLAIMED.value,
                NotificationDeliveryModel.attempt_count == 3,
                NotificationDeliveryModel.claim_expires_at <= func.now(),
            )
            .values(
                status=NotificationStatus.FAILED_FINAL.value,
                claim_token=None,
                claim_expires_at=None,
                updated_at=func.now(),
            )
        ),
    )
    return result.rowcount or 0


async def claim_one_eligible_notification(
    session: AsyncSession, *, now: datetime | None = None
) -> NotificationDeliveryModel | None:
    """Lock one due or expired row while leaving claim mutation to the service."""

    database_now = now if now is not None else func.now()
    eligible_pending = and_(
        NotificationDeliveryModel.status == NotificationStatus.PENDING.value,
        NotificationDeliveryModel.attempt_count < 3,
        NotificationDeliveryModel.next_attempt_at <= database_now,
    )
    eligible_expired = and_(
        NotificationDeliveryModel.status == NotificationStatus.CLAIMED.value,
        NotificationDeliveryModel.claim_expires_at <= database_now,
        NotificationDeliveryModel.attempt_count < 3,
    )
    statement = (
        select(NotificationDeliveryModel)
        .where(or_(eligible_pending, eligible_expired))
        .order_by(
            NotificationDeliveryModel.next_attempt_at,
            NotificationDeliveryModel.created_at,
            NotificationDeliveryModel.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return cast(NotificationDeliveryModel | None, await session.scalar(statement))


async def get_notification_delivery_for_update(
    session: AsyncSession, notification_id: UUID
) -> NotificationDeliveryModel | None:
    """Fetch and lock one delivery row for an outcome transition."""

    statement = (
        select(NotificationDeliveryModel)
        .where(NotificationDeliveryModel.id == notification_id)
        .with_for_update()
    )
    return cast(NotificationDeliveryModel | None, await session.scalar(statement))
