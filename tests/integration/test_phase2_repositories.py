"""Real-PostgreSQL tests for concrete Phase 2 repository operations."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from opsflow.domain import (
    AuditEvent,
    Order,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.persistence.models import (
    AuditEventModel,
    OrderModel,
    ValidationIssueModel,
)
from opsflow.persistence.repositories import (
    OrderSummary,
    PersistedOrder,
    get_audit_events,
    get_order,
    insert_order_graph,
    list_orders,
)
from opsflow.settings import Settings


def test_minimal_order_graph_is_persisted_and_reconstructed() -> None:
    asyncio.run(_assert_minimal_order_graph())


def test_populated_order_graph_reconstructs_children_and_validation_issues() -> None:
    asyncio.run(_assert_populated_order_graph())


def test_missing_order_returns_none() -> None:
    asyncio.run(_assert_missing_order())


def test_list_returns_summaries_with_deterministic_pagination_and_total() -> None:
    asyncio.run(_assert_list_behavior())


def test_audit_events_are_domain_records_in_deterministic_order() -> None:
    asyncio.run(_assert_audit_behavior())


def test_insert_order_graph_does_not_commit_for_the_caller() -> None:
    asyncio.run(_assert_transaction_ownership())


async def _assert_minimal_order_graph() -> None:
    order = Order.received(id=uuid4())
    created_at = datetime(2030, 1, 1, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, created_at)
            await session.commit()
            persisted = await get_order(session, order.id)

            assert isinstance(persisted, PersistedOrder)
            assert persisted.order == order
            assert persisted.created_at == created_at
            assert persisted.validation_issues == ()
            assert not isinstance(persisted.order, OrderModel)
    finally:
        await engine.dispose()


async def _assert_populated_order_graph() -> None:
    line_a = OrderLine(
        id=uuid4(),
        sku="SKU-A",
        description="A",
        quantity=Decimal("2.50"),
        submitted_price=Decimal("10.00"),
        trusted_catalogue_price=Decimal("11.00"),
    )
    line_b = OrderLine(
        id=uuid4(),
        sku=None,
        description="B",
        quantity=Decimal("1"),
        submitted_price=None,
        trusted_catalogue_price=None,
    )
    document_a = SourceDocument(
        id=uuid4(),
        document_type=SourceDocumentType.PDF,
        name="a.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        message_id=None,
        storage_reference="storage/a",
        metadata=(("source", "archive"), ("source", "email")),
    )
    document_b = SourceDocument(
        id=uuid4(),
        document_type=SourceDocumentType.FORM,
        name="form",
        mime_type="application/json",
        sha256="b" * 64,
        message_id="message-b",
        storage_reference=None,
        metadata=(("source", "form"),),
    )
    order = Order.received(
        id=uuid4(),
        customer_reference="customer",
        po_number="po-1",
        currency="USD",
        lines=(line_a, line_b),
        source_documents=(document_a, document_b),
    )
    issue_a = ValidationIssue(
        rule_code="RULE-A",
        severity=ValidationSeverity.WARNING,
        field="po_number",
        expected="present",
        actual=None,
        explanation="PO is absent.",
    )
    issue_b = ValidationIssue(
        rule_code="RULE-B",
        severity=ValidationSeverity.ERROR,
        field="currency",
        expected="USD",
        actual="EUR",
        explanation="Currency differs.",
    )
    created_at = datetime(2030, 1, 2, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, created_at)
            session.add_all(
                [
                    ValidationIssueModel(
                        order_id=order.id,
                        position=1,
                        rule_code=issue_b.rule_code,
                        severity=issue_b.severity.value,
                        field=issue_b.field,
                        expected=issue_b.expected,
                        actual=issue_b.actual,
                        explanation=issue_b.explanation,
                    ),
                    ValidationIssueModel(
                        order_id=order.id,
                        position=0,
                        rule_code=issue_a.rule_code,
                        severity=issue_a.severity.value,
                        field=issue_a.field,
                        expected=issue_a.expected,
                        actual=issue_a.actual,
                        explanation=issue_a.explanation,
                    ),
                ]
            )
            await session.commit()

            persisted = await get_order(session, order.id)

            assert persisted is not None
            assert persisted.order == order
            assert [line.id for line in persisted.order.lines] == [line_a.id, line_b.id]
            assert [document.id for document in persisted.order.source_documents] == [
                document_a.id,
                document_b.id,
            ]
            assert persisted.order.lines[0].quantity == Decimal("2.50")
            assert persisted.order.source_documents[0].metadata == document_a.metadata
            assert persisted.validation_issues == (issue_a, issue_b)
            assert all(isinstance(issue, ValidationIssue) for issue in persisted.validation_issues)
    finally:
        await engine.dispose()


async def _assert_missing_order() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            assert await get_order(session, uuid4()) is None
    finally:
        await engine.dispose()


async def _assert_list_behavior() -> None:
    before_engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(before_engine) as session:
            before_total = await session.scalar(select(func.count()).select_from(OrderModel))
    finally:
        await before_engine.dispose()

    order_low = Order.received(id=UUID("11111111-1111-4111-8111-111111111111"), po_number="low")
    order_high = Order.received(id=UUID("33333333-3333-4333-8333-333333333333"), po_number="high")
    order_middle = Order.received(
        id=UUID("22222222-2222-4222-8222-222222222222"), po_number="middle"
    )
    created_at = datetime(2030, 2, 1, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            for order in (order_low, order_high, order_middle):
                await insert_order_graph(session, order, created_at)
            await session.commit()

            items, total = await list_orders(session, limit=2, offset=1)

            assert total == before_total + 3
            assert items == (
                OrderSummary(
                    id=order_middle.id,
                    customer_reference=None,
                    po_number="middle",
                    order_date=None,
                    requested_delivery_date=None,
                    currency=None,
                    state=order_middle.state,
                    created_at=created_at,
                ),
                OrderSummary(
                    id=order_low.id,
                    customer_reference=None,
                    po_number="low",
                    order_date=None,
                    requested_delivery_date=None,
                    currency=None,
                    state=order_low.state,
                    created_at=created_at,
                ),
            )
            assert all(isinstance(item, OrderSummary) for item in items)
            assert all(not isinstance(item, Order) for item in items)
            assert not hasattr(items[0], "lines")
    finally:
        await engine.dispose()


async def _assert_audit_behavior() -> None:
    order = Order.received(id=uuid4())
    first = AuditEvent(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        order_id=order.id,
        event_type="SECOND",
        actor="system",
        occurred_at=datetime(2030, 3, 1, tzinfo=UTC),
        description="second",
    )
    second = AuditEvent(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        order_id=order.id,
        event_type="FIRST",
        actor="system",
        occurred_at=first.occurred_at,
        description="first",
    )
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, datetime(2030, 3, 1, tzinfo=UTC))
            session.add_all(
                [
                    AuditEventModel(
                        id=first.id,
                        order_id=first.order_id,
                        event_type=first.event_type,
                        actor=first.actor,
                        occurred_at=first.occurred_at,
                        description=first.description,
                    ),
                    AuditEventModel(
                        id=second.id,
                        order_id=second.order_id,
                        event_type=second.event_type,
                        actor=second.actor,
                        occurred_at=second.occurred_at,
                        description=second.description,
                    ),
                ]
            )
            await session.commit()

            events = await get_audit_events(session, order.id)

            assert events == (first, second)
            assert all(isinstance(event, AuditEvent) for event in events)
            assert all(not isinstance(event, AuditEventModel) for event in events)
    finally:
        await engine.dispose()


async def _assert_transaction_ownership() -> None:
    order = Order.received(id=uuid4())
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, datetime(2030, 4, 1, tzinfo=UTC))
            assert session.in_transaction()

            async with AsyncSession(engine) as other_session:
                assert await other_session.get(OrderModel, order.id) is None
            await session.rollback()

            assert await session.get(OrderModel, order.id) is None
    finally:
        await engine.dispose()
