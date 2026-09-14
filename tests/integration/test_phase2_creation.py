"""Real-PostgreSQL tests for atomic idempotent order creation."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from opsflow.application.errors import IdempotencyConflictError
from opsflow.application.orders import (
    CreateLineInput,
    CreateOrderInput,
    CreateSourceDocumentInput,
    create_order,
    fingerprint_order_request,
)
from opsflow.domain import SourceDocumentType
from opsflow.persistence.models import (
    AuditEventModel,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    SourceDocumentModel,
)
from opsflow.persistence.repositories import get_audit_events, get_idempotency_record, get_order
from opsflow.settings import Settings


def test_minimal_create_persists_received_order_audit_and_idempotency() -> None:
    asyncio.run(_assert_minimal_create())


def test_populated_create_persists_generated_children_and_semantic_values() -> None:
    asyncio.run(_assert_populated_create())


def test_sequential_same_key_same_input_replays_original_result_without_duplicates() -> None:
    asyncio.run(_assert_sequential_replay())


def test_same_key_different_input_raises_conflict_and_keeps_only_winner() -> None:
    asyncio.run(_assert_sequential_conflict())


def _minimal_request() -> CreateOrderInput:
    return CreateOrderInput()


def _populated_request() -> CreateOrderInput:
    return CreateOrderInput(
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2030, 1, 2),
        requested_delivery_date=date(2030, 1, 10),
        currency="USD",
        lines=(
            CreateLineInput(
                sku="SKU-1",
                description="Widget",
                quantity=Decimal("2.50"),
                submitted_price=Decimal("10.00"),
                trusted_catalogue_price=Decimal("11.00"),
            ),
        ),
        source_documents=(
            CreateSourceDocumentInput(
                document_type=SourceDocumentType.FORM,
                name="intake-form",
                mime_type="application/json",
                sha256="a" * 64,
                message_id="message-1",
                storage_reference="synthetic://form/1",
                metadata=(("source", "form"), ("source", "archive")),
            ),
        ),
    )


async def _assert_minimal_create() -> None:
    request = _minimal_request()
    key = f"minimal-{uuid4()}"
    now = datetime(2030, 2, 1, 12, 30, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            result = await create_order(session, request, key, now=now)

            assert result.order.state.value == "RECEIVED"
            assert result.order.failure_origin is None
            assert result.created_at == now
            assert result.validation_issues == ()

            events = await get_audit_events(session, result.order.id)
            assert len(events) == 1
            assert events[0].event_type == "ORDER_RECEIVED"
            assert events[0].actor == "system"
            assert events[0].description == "Order received through API intake."
            assert events[0].occurred_at == now
            assert events[0].occurred_at.tzinfo is not None
            assert events[0].occurred_at.utcoffset() is not None

            idempotency = await get_idempotency_record(session, key)
            assert idempotency is not None
            assert idempotency.order_id == result.order.id
            assert idempotency.request_fingerprint == fingerprint_order_request(request)
            assert await _count(session, OrderModel, OrderModel.id == result.order.id) == 1
            assert (
                await _count(session, AuditEventModel, AuditEventModel.order_id == result.order.id)
                == 1
            )
            assert (
                await _count(
                    session,
                    OrderCreationIdempotencyModel,
                    OrderCreationIdempotencyModel.idempotency_key == key,
                )
                == 1
            )
    finally:
        await engine.dispose()


async def _assert_populated_create() -> None:
    request = _populated_request()
    key = f"populated-{uuid4()}"
    now = datetime(2030, 3, 1, 12, 30, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            result = await create_order(session, request, key, now=now)

            assert len(result.order.lines) == 1
            assert len(result.order.source_documents) == 1
            assert result.order.lines[0].id is not None
            assert result.order.source_documents[0].id is not None
            assert result.order.lines[0].quantity == Decimal("2.50")
            assert result.order.source_documents[0].metadata == (
                ("source", "form"),
                ("source", "archive"),
            )
            assert (
                await _count(session, OrderLineModel, OrderLineModel.order_id == result.order.id)
                == 1
            )
            assert (
                await _count(
                    session,
                    SourceDocumentModel,
                    SourceDocumentModel.order_id == result.order.id,
                )
                == 1
            )
            assert (
                await _count(session, AuditEventModel, AuditEventModel.order_id == result.order.id)
                == 1
            )
            assert await get_idempotency_record(session, key) is not None
    finally:
        await engine.dispose()


async def _assert_sequential_replay() -> None:
    request = _populated_request()
    key = f"replay-{uuid4()}"
    first_now = datetime(2030, 4, 1, 12, 30, tzinfo=UTC)
    second_now = datetime(2030, 4, 2, 12, 30, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            first = await create_order(session, request, key, now=first_now)
            second = await create_order(session, request, key, now=second_now)

            assert second == first
            assert second.order.id == first.order.id
            assert second.created_at == first_now
            assert await _count(session, OrderModel, OrderModel.id == first.order.id) == 1
            assert (
                await _count(session, OrderLineModel, OrderLineModel.order_id == first.order.id)
                == 1
            )
            assert (
                await _count(
                    session, SourceDocumentModel, SourceDocumentModel.order_id == first.order.id
                )
                == 1
            )
            assert (
                await _count(session, AuditEventModel, AuditEventModel.order_id == first.order.id)
                == 1
            )
            assert (
                await _count(
                    session,
                    OrderCreationIdempotencyModel,
                    OrderCreationIdempotencyModel.idempotency_key == key,
                )
                == 1
            )
            assert await get_order(session, first.order.id) == first
    finally:
        await engine.dispose()


async def _assert_sequential_conflict() -> None:
    winner_request = _minimal_request()
    conflicting_request = CreateOrderInput(customer_reference="different")
    key = f"conflict-{uuid4()}"
    now = datetime(2030, 5, 1, 12, 30, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            before = await _table_counts(session)
            await session.rollback()
            winner = await create_order(session, winner_request, key, now=now)

            with pytest.raises(IdempotencyConflictError) as error:
                await create_order(session, conflicting_request, key, now=now)
            assert error.value.idempotency_key == key

            after = await _table_counts(session)
            assert after["orders"] == before["orders"] + 1
            assert after["order_lines"] == before["order_lines"]
            assert after["source_documents"] == before["source_documents"]
            assert after["audit_events"] == before["audit_events"] + 1
            assert after["order_creation_idempotency"] == before["order_creation_idempotency"] + 1
            record = await get_idempotency_record(session, key)
            assert record is not None
            assert record.order_id == winner.order.id
            assert record.request_fingerprint == fingerprint_order_request(winner_request)
            assert await get_order(session, winner.order.id) == winner
    finally:
        await engine.dispose()


async def _count(session: AsyncSession, model: type[object], condition: object) -> int:
    result = await session.scalar(select(func.count()).select_from(model).where(condition))
    return int(result or 0)


async def _table_counts(session: AsyncSession) -> dict[str, int]:
    return {
        "orders": await _count(session, OrderModel, True),
        "order_lines": await _count(session, OrderLineModel, True),
        "source_documents": await _count(session, SourceDocumentModel, True),
        "audit_events": await _count(session, AuditEventModel, True),
        "order_creation_idempotency": await _count(session, OrderCreationIdempotencyModel, True),
    }
