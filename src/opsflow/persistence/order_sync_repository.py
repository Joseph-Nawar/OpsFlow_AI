"""Transaction-neutral persistence operations for durable order synchronization."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.persistence.models import OrderModel, OrderSyncModel


async def insert_order_sync_intent(
    session: AsyncSession,
    order_id: UUID,
    created_at: datetime,
) -> None:
    """Flush one sync intent inside the caller's approval transaction."""

    session.add(
        OrderSyncModel(
            order_id=order_id,
            claim_token=None,
            claim_expires_at=None,
            attempt_count=0,
            retry_generation=0,
            next_attempt_at=created_at,
            odoo_sale_order_id=None,
            odoo_sale_order_name=None,
            hubspot_company_id=None,
            hubspot_deal_id=None,
            hubspot_association_confirmed_at=None,
            in_flight_step=None,
            last_failure_step=None,
            last_failure_code=None,
            last_attempt_at=None,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await session.flush()


async def get_order_sync_for_update(
    session: AsyncSession,
    order_id: UUID,
) -> OrderSyncModel | None:
    """Lock an order's sync row for a caller-owned atomic mutation."""

    return cast(
        OrderSyncModel | None,
        await session.scalar(
            select(OrderSyncModel).where(OrderSyncModel.order_id == order_id).with_for_update()
        ),
    )


async def reset_order_sync_for_human_retry(
    session: AsyncSession,
    order_id: UUID,
) -> bool:
    """Start a new retry generation, preserving all successful and uncertain steps."""

    row = await get_order_sync_for_update(session, order_id)
    if row is None:
        return False
    row.retry_generation += 1
    row.attempt_count = 0
    row.next_attempt_at = func.now()
    row.claim_token = None
    row.claim_expires_at = None
    row.updated_at = func.now()
    await session.flush()
    await session.refresh(row, attribute_names=["next_attempt_at", "updated_at"])
    return True


async def claim_one_eligible_order_sync(
    session: AsyncSession,
) -> tuple[OrderSyncModel, OrderModel] | None:
    """Lock the next due order and intent, skipping rows another worker owns."""

    approved = and_(
        OrderModel.state == "APPROVED",
        OrderSyncModel.claim_token.is_(None),
        OrderSyncModel.next_attempt_at <= func.now(),
    )
    syncing_unclaimed = and_(
        OrderModel.state == "SYNCING",
        OrderSyncModel.claim_token.is_(None),
        OrderSyncModel.next_attempt_at <= func.now(),
        OrderSyncModel.attempt_count < 3,
    )
    syncing_expired = and_(
        OrderModel.state == "SYNCING",
        OrderSyncModel.claim_token.is_not(None),
        OrderSyncModel.claim_expires_at <= func.now(),
        OrderSyncModel.attempt_count < 3,
    )
    statement = (
        select(OrderSyncModel, OrderModel)
        .join(OrderModel, OrderModel.id == OrderSyncModel.order_id)
        .where(or_(approved, syncing_unclaimed, syncing_expired))
        .order_by(
            OrderSyncModel.next_attempt_at,
            OrderSyncModel.created_at,
            OrderSyncModel.order_id,
        )
        .limit(1)
        .with_for_update(skip_locked=True, of=[OrderModel, OrderSyncModel])
    )
    result = await session.execute(statement)
    selected = result.first()
    if selected is None:
        return None
    return selected[0], selected[1]


async def get_order_sync_claim_for_update(
    session: AsyncSession,
    order_id: UUID,
) -> tuple[OrderSyncModel, OrderModel] | None:
    """Lock one order before its sync row, matching human Retry's lock order."""

    order = await session.scalar(
        select(OrderModel).where(OrderModel.id == order_id).with_for_update()
    )
    if order is None:
        return None
    sync = await session.scalar(
        select(OrderSyncModel).where(OrderSyncModel.order_id == order_id).with_for_update()
    )
    if sync is None:
        return None
    return sync, order


async def get_order_sync_state(session: AsyncSession, order_id: UUID) -> str | None:
    """Read authoritative lifecycle state without provider-specific details."""

    return cast(
        str | None,
        await session.scalar(select(OrderModel.state).where(OrderModel.id == order_id)),
    )
