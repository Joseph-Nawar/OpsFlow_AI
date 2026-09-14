"""Real-PostgreSQL tests for thin Phase 2 application read operations."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from opsflow.application.errors import OrderNotFoundError
from opsflow.application.orders import (
    get_order,
    get_order_audit,
    list_orders,
)
from opsflow.domain import AuditEvent, Order
from opsflow.persistence.models import AuditEventModel, OrderModel
from opsflow.persistence.repositories import OrderSummary, PersistedOrder, insert_order_graph
from opsflow.settings import Settings


def test_application_get_order_returns_existing_detail() -> None:
    asyncio.run(_assert_existing_detail())


def test_application_get_order_raises_for_missing_order() -> None:
    asyncio.run(_assert_missing_detail())


def test_application_list_orders_preserves_repository_result() -> None:
    asyncio.run(_assert_list_passthrough())


def test_application_get_order_audit_returns_empty_for_existing_order() -> None:
    asyncio.run(_assert_empty_audit_for_existing_order())


def test_application_get_order_audit_returns_ordered_events() -> None:
    asyncio.run(_assert_existing_audit())


def test_application_get_order_audit_raises_for_missing_order() -> None:
    asyncio.run(_assert_missing_audit_target())


async def _assert_existing_detail() -> None:
    order = Order.received(id=uuid4())
    created_at = datetime(2030, 5, 1, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, created_at)
            await session.commit()

            result = await get_order(session, order.id)

            assert isinstance(result, PersistedOrder)
            assert result.order == order
            assert result.created_at == created_at
            assert not isinstance(result.order, OrderModel)
    finally:
        await engine.dispose()


async def _assert_missing_detail() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            try:
                await get_order(session, uuid4())
            except OrderNotFoundError as error:
                assert error.order_id
            else:
                raise AssertionError("missing order did not raise OrderNotFoundError")
    finally:
        await engine.dispose()


async def _assert_list_passthrough() -> None:
    orders = (
        Order.received(id=UUID("44444444-4444-4444-8444-444444444444")),
        Order.received(id=UUID("55555555-5555-4555-8555-555555555555")),
    )
    created_at = datetime(2030, 6, 1, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            for order in orders:
                await insert_order_graph(session, order, created_at)
            await session.commit()

            items, total = await list_orders(session, limit=2, offset=0)

            assert total >= 2
            assert all(isinstance(item, OrderSummary) for item in items)
            assert all(not isinstance(item, OrderModel) for item in items)
            assert all(not hasattr(item, "lines") for item in items)
            assert tuple(item.id for item in items) == (orders[1].id, orders[0].id)
    finally:
        await engine.dispose()


async def _assert_empty_audit_for_existing_order() -> None:
    order = Order.received(id=uuid4())
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, datetime(2030, 7, 1, tzinfo=UTC))
            await session.commit()

            assert await get_order_audit(session, order.id) == ()
    finally:
        await engine.dispose()


async def _assert_existing_audit() -> None:
    order = Order.received(id=uuid4())
    occurred_at = datetime(2030, 8, 1, tzinfo=UTC)
    first = AuditEvent(
        id=UUID("66666666-6666-4666-8666-666666666666"),
        order_id=order.id,
        event_type="FIRST",
        actor="system",
        occurred_at=occurred_at,
        description="first",
    )
    second = AuditEvent(
        id=UUID("77777777-7777-4777-8777-777777777777"),
        order_id=order.id,
        event_type="SECOND",
        actor="system",
        occurred_at=occurred_at,
        description="second",
    )
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, occurred_at)
            session.add_all(
                [
                    AuditEventModel(
                        id=second.id,
                        order_id=second.order_id,
                        event_type=second.event_type,
                        actor=second.actor,
                        occurred_at=second.occurred_at,
                        description=second.description,
                    ),
                    AuditEventModel(
                        id=first.id,
                        order_id=first.order_id,
                        event_type=first.event_type,
                        actor=first.actor,
                        occurred_at=first.occurred_at,
                        description=first.description,
                    ),
                ]
            )
            await session.commit()

            events = await get_order_audit(session, order.id)

            assert events == (first, second)
            assert all(not isinstance(event, AuditEventModel) for event in events)
            assert all(isinstance(event, AuditEvent) for event in events)
    finally:
        await engine.dispose()


async def _assert_missing_audit_target() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            try:
                await get_order_audit(session, uuid4())
            except OrderNotFoundError as error:
                assert error.order_id
            else:
                raise AssertionError("missing audit target did not raise OrderNotFoundError")
    finally:
        await engine.dispose()
