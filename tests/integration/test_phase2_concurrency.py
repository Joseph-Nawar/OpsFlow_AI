"""Real-PostgreSQL concurrency and rollback proofs for order creation."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

import opsflow.application.orders as orders_module
from opsflow.application.errors import IdempotencyConflictError
from opsflow.application.orders import (
    CreateLineInput,
    CreateOrderDisposition,
    CreateOrderInput,
    CreateOrderResult,
    CreateSourceDocumentInput,
    create_order,
    create_order_with_disposition,
)
from opsflow.domain import AuditEvent, SourceDocumentType
from opsflow.persistence.models import (
    AuditEventModel,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    SourceDocumentModel,
)
from opsflow.settings import Settings


def test_concurrent_identical_creates_return_one_durable_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_concurrent_identical_creates(monkeypatch))


def test_concurrent_conflicting_creates_leave_only_the_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_concurrent_conflicting_creates(monkeypatch))


def test_create_failure_rolls_back_every_required_row(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_assert_create_failure_rolls_back(monkeypatch))


def test_non_idempotency_integrity_error_is_not_classified_as_conflict() -> None:
    asyncio.run(_assert_non_idempotency_integrity_error_propagates())


def _request() -> CreateOrderInput:
    return CreateOrderInput(
        customer_reference="CUST-CONCURRENCY",
        po_number="PO-CONCURRENCY",
        currency="USD",
        lines=(
            CreateLineInput(
                sku="SKU-CONCURRENCY",
                description="Synthetic concurrency fixture",
                quantity=Decimal("2.50"),
                submitted_price=Decimal("10.00"),
                trusted_catalogue_price=Decimal("11.00"),
            ),
        ),
        source_documents=(
            CreateSourceDocumentInput(
                document_type=SourceDocumentType.FORM,
                name="concurrency-form",
                mime_type="application/json",
                sha256="a" * 64,
                metadata=(("source", "test"), ("source", "archive")),
            ),
        ),
    )


async def _assert_concurrent_identical_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    key = f"concurrent-identical-{uuid4()}"
    engine = create_async_engine(Settings().database_url)
    barrier = asyncio.Barrier(2)
    original_insert = orders_module.insert_idempotency_record

    async def synchronized_insert(
        session: AsyncSession,
        idempotency_key: str,
        request_fingerprint: str,
        order_id: UUID,
        created_at: datetime,
    ) -> None:
        await barrier.wait()
        await original_insert(session, idempotency_key, request_fingerprint, order_id, created_at)

    monkeypatch.setattr(orders_module, "insert_idempotency_record", synchronized_insert)
    try:
        before = await _table_counts(engine)
        async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
            first, second = await asyncio.gather(
                create_order_with_disposition(first_session, request, key),
                create_order_with_disposition(second_session, request, key),
            )

            assert isinstance(first, CreateOrderResult)
            assert isinstance(second, CreateOrderResult)
            assert {first.disposition, second.disposition} == {
                CreateOrderDisposition.CREATED_BY_THIS_COMMAND,
                CreateOrderDisposition.REPLAYED_EXISTING,
            }
            assert first.persisted.order.id == second.persisted.order.id
            assert not first_session.in_transaction()
            assert not second_session.in_transaction()

            assert (
                await first_session.scalar(select(func.count()).select_from(OrderModel)) is not None
            )
            assert (
                await second_session.scalar(select(func.count()).select_from(OrderModel))
                is not None
            )
            await first_session.rollback()
            await second_session.rollback()

        after = await _table_counts(engine)
        assert after["orders"] == before["orders"] + 1
        assert after["order_lines"] == before["order_lines"] + len(request.lines)
        assert after["source_documents"] == before["source_documents"] + len(
            request.source_documents
        )
        assert after["audit_events"] == before["audit_events"] + 1
        assert after["order_creation_idempotency"] == before["order_creation_idempotency"] + 1
        async with AsyncSession(engine) as verify_session:
            order_id = first.persisted.order.id
            assert await _count(
                verify_session, OrderLineModel, OrderLineModel.order_id == order_id
            ) == len(request.lines)
            assert await _count(
                verify_session,
                SourceDocumentModel,
                SourceDocumentModel.order_id == order_id,
            ) == len(request.source_documents)
            assert (
                await _count(
                    verify_session,
                    AuditEventModel,
                    AuditEventModel.order_id == order_id,
                    AuditEventModel.event_type == "ORDER_RECEIVED",
                )
                == 1
            )
    finally:
        await engine.dispose()


async def _assert_concurrent_conflicting_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    winner_request = _request()
    conflicting_request = CreateOrderInput(customer_reference="A-different-request")
    key = f"concurrent-conflict-{uuid4()}"
    engine = create_async_engine(Settings().database_url)
    barrier = asyncio.Barrier(2)
    original_insert = orders_module.insert_idempotency_record

    async def synchronized_insert(
        session: AsyncSession,
        idempotency_key: str,
        request_fingerprint: str,
        order_id: UUID,
        created_at: datetime,
    ) -> None:
        await barrier.wait()
        await original_insert(session, idempotency_key, request_fingerprint, order_id, created_at)

    monkeypatch.setattr(orders_module, "insert_idempotency_record", synchronized_insert)
    try:
        before = await _table_counts(engine)
        async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
            results = await asyncio.gather(
                create_order_with_disposition(first_session, winner_request, key),
                create_order_with_disposition(second_session, conflicting_request, key),
                return_exceptions=True,
            )

            successful = [result for result in results if isinstance(result, CreateOrderResult)]
            conflicts = [
                result for result in results if isinstance(result, IdempotencyConflictError)
            ]
            assert len(successful) == 1
            assert successful[0].disposition is CreateOrderDisposition.CREATED_BY_THIS_COMMAND
            assert len(conflicts) == 1
            assert conflicts[0].idempotency_key == key
            assert not first_session.in_transaction()
            assert not second_session.in_transaction()
            assert (
                await first_session.scalar(select(func.count()).select_from(OrderModel)) is not None
            )
            assert (
                await second_session.scalar(select(func.count()).select_from(OrderModel))
                is not None
            )
            await first_session.rollback()
            await second_session.rollback()

        after = await _table_counts(engine)
        winner = successful[0].persisted
        assert after["orders"] == before["orders"] + 1
        assert after["order_lines"] == before["order_lines"] + len(winner.order.lines)
        assert after["source_documents"] == before["source_documents"] + len(
            winner.order.source_documents
        )
        assert after["audit_events"] == before["audit_events"] + 1
        assert after["order_creation_idempotency"] == before["order_creation_idempotency"] + 1
    finally:
        await engine.dispose()


async def _assert_create_failure_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    key = f"rollback-{uuid4()}"
    engine = create_async_engine(Settings().database_url)
    original_insert = orders_module.insert_audit_event

    async def failing_insert(session: AsyncSession, event: AuditEvent) -> None:
        await original_insert(session, event)
        raise RuntimeError("injected post-write failure")

    monkeypatch.setattr(orders_module, "insert_audit_event", failing_insert)
    try:
        before = await _table_counts(engine)
        async with AsyncSession(engine) as session:
            with pytest.raises(RuntimeError, match="injected post-write failure"):
                await create_order(session, request, key, now=datetime(2030, 1, 1, tzinfo=UTC))
            assert not session.in_transaction()
            assert (
                await session.scalar(select(func.count()).select_from(OrderModel))
                == before["orders"]
            )
            await session.rollback()

        after = await _table_counts(engine)
        assert after == before
    finally:
        await engine.dispose()


async def _assert_non_idempotency_integrity_error_propagates() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(IntegrityError):
                await create_order(session, CreateOrderInput(), " ")
            assert not session.in_transaction()
            assert await session.scalar(select(func.count()).select_from(OrderModel)) is not None
            await session.rollback()
    finally:
        await engine.dispose()


async def _table_counts(engine: AsyncEngine) -> dict[str, int]:
    async with AsyncSession(engine) as session:
        return {
            "orders": await _count(session, OrderModel),
            "order_lines": await _count(session, OrderLineModel),
            "source_documents": await _count(session, SourceDocumentModel),
            "audit_events": await _count(session, AuditEventModel),
            "order_creation_idempotency": await _count(session, OrderCreationIdempotencyModel),
        }


async def _count(session: AsyncSession, model: type[object], *criteria: object) -> int:
    result = await session.scalar(select(func.count()).select_from(model).where(*criteria))
    return int(result or 0)
