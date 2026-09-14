"""Real-PostgreSQL round-trip tests for Phase 1 persistence mapping."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
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
from opsflow.persistence.mappers import (
    audit_event_from_model,
    line_to_model,
    order_from_models,
    order_to_model,
    source_document_to_model,
    validation_issue_from_model,
)
from opsflow.persistence.models import (
    AuditEventModel,
    OrderLineModel,
    OrderModel,
    SourceDocumentModel,
    ValidationIssueModel,
)
from opsflow.settings import Settings


def test_minimal_received_order_round_trips_through_postgresql() -> None:
    asyncio.run(_round_trip_minimal())


def test_populated_order_children_issues_and_audit_round_trip_through_postgresql() -> None:
    asyncio.run(_round_trip_populated())


async def _round_trip_minimal() -> None:
    order = Order.received(id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
    created_at = datetime(2026, 9, 14, 11, 0, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            session.add(order_to_model(order, created_at))
            await session.commit()

            row = await session.get(OrderModel, order.id)
            assert row is not None
            assert order_from_models(row, [], []) == order
            assert row.created_at == created_at
    finally:
        await engine.dispose()


async def _round_trip_populated() -> None:
    first_line = OrderLine(
        id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        sku="SKU-2",
        description="Second line",
        quantity=Decimal("2.500"),
        submitted_price=Decimal("9.90"),
        trusted_catalogue_price=Decimal("10.00"),
    )
    second_line = OrderLine(
        id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        sku=None,
        description="First line",
        quantity=Decimal("1"),
        submitted_price=None,
        trusted_catalogue_price=None,
    )
    first_document = SourceDocument(
        id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256="d" * 64,
        message_id=None,
        storage_reference="documents/purchase-order.pdf",
        metadata=(("source", "archive"), ("source", "email")),
    )
    second_document = SourceDocument(
        id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        document_type=SourceDocumentType.FORM,
        name="intake-form",
        mime_type="application/json",
        sha256="e" * 64,
        message_id="form-1",
        storage_reference=None,
        metadata=(("source", "form"),),
    )
    order = Order.received(
        id=UUID("99999999-9999-4999-8999-999999999999"),
        customer_reference="CUST-2",
        po_number="PO-2",
        order_date=date(2026, 9, 14),
        requested_delivery_date=date(2026, 10, 1),
        currency="EUR",
        lines=(first_line, second_line),
        source_documents=(first_document, second_document),
    )
    issue = ValidationIssue(
        rule_code="MISSING_CUSTOMER",
        severity=ValidationSeverity.ERROR,
        field="customer_reference",
        expected="present",
        actual=None,
        explanation="The customer reference is absent.",
    )
    audit = AuditEvent(
        id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        order_id=order.id,
        event_type="ORDER_RECEIVED",
        actor="system",
        occurred_at=datetime(2026, 9, 14, 11, 1, tzinfo=UTC),
        description="Order received through API intake.",
    )
    created_at = datetime(2026, 9, 14, 11, 0, tzinfo=UTC)
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            session.add(order_to_model(order, created_at))
            session.add_all(
                [
                    line_to_model(order.id, 0, first_line),
                    line_to_model(order.id, 1, second_line),
                    source_document_to_model(order.id, 0, first_document),
                    source_document_to_model(order.id, 1, second_document),
                    ValidationIssueModel(
                        order_id=order.id,
                        position=0,
                        rule_code=issue.rule_code,
                        severity=issue.severity.value,
                        field=issue.field,
                        expected=issue.expected,
                        actual=issue.actual,
                        explanation=issue.explanation,
                    ),
                    AuditEventModel(
                        id=audit.id,
                        order_id=audit.order_id,
                        event_type=audit.event_type,
                        actor=audit.actor,
                        occurred_at=audit.occurred_at,
                        description=audit.description,
                    ),
                ]
            )
            await session.commit()

            order_row = await session.get(OrderModel, order.id)
            assert order_row is not None
            line_rows = (
                await session.scalars(
                    select(OrderLineModel)
                    .where(OrderLineModel.order_id == order.id)
                    .order_by(OrderLineModel.position.asc())
                )
            ).all()
            document_rows = (
                await session.scalars(
                    select(SourceDocumentModel)
                    .where(SourceDocumentModel.order_id == order.id)
                    .order_by(SourceDocumentModel.position.asc())
                )
            ).all()
            issue_row = await session.get(ValidationIssueModel, (order.id, 0))
            audit_row = await session.get(AuditEventModel, audit.id)

            assert order_from_models(order_row, line_rows, document_rows) == order
            assert [row.position for row in line_rows] == [0, 1]
            assert [row.position for row in document_rows] == [0, 1]
            assert order_from_models(order_row, line_rows, document_rows).lines == (
                first_line,
                second_line,
            )
            restored_order = order_from_models(order_row, line_rows, document_rows)
            assert restored_order.source_documents[0].metadata == (
                ("source", "archive"),
                ("source", "email"),
            )
            assert issue_row is not None
            assert validation_issue_from_model(issue_row) == issue
            assert audit_row is not None
            assert audit_event_from_model(audit_row) == audit
            assert audit_row.occurred_at.tzinfo is not None
            assert audit_row.occurred_at.utcoffset() is not None
    finally:
        await engine.dispose()
