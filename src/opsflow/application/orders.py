"""Thin application operations for durable order reads."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import AuditEvent
from opsflow.persistence.repositories import OrderSummary, PersistedOrder
from opsflow.persistence.repositories import get_audit_events as repository_get_audit_events
from opsflow.persistence.repositories import get_order as repository_get_order
from opsflow.persistence.repositories import list_orders as repository_list_orders

from .errors import OrderNotFoundError


async def get_order(session: AsyncSession, order_id: UUID) -> PersistedOrder:
    """Return one persisted order or raise when it is missing."""

    result = await repository_get_order(session, order_id)
    if result is None:
        raise OrderNotFoundError(order_id)
    return result


async def list_orders(
    session: AsyncSession, limit: int, offset: int
) -> tuple[tuple[OrderSummary, ...], int]:
    """Pass through deterministic repository summaries and total count."""

    return await repository_list_orders(session, limit, offset)


async def get_order_audit(session: AsyncSession, order_id: UUID) -> tuple[AuditEvent, ...]:
    """Return audit events for an existing order, including an empty history."""

    if await repository_get_order(session, order_id) is None:
        raise OrderNotFoundError(order_id)
    return await repository_get_audit_events(session, order_id)
