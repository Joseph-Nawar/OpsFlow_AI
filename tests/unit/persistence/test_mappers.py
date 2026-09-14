"""Unit tests for explicit Phase 1 domain and persistence mapping."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from opsflow.domain import (
    AuditEvent,
    DomainValidationError,
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
    source_document_from_model,
    source_document_to_model,
    validation_issue_from_model,
)
from opsflow.persistence.models import (
    AuditEventModel,
    SourceDocumentModel,
    ValidationIssueModel,
)

ORDER_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 9, 14, 10, 30, tzinfo=UTC)


def test_minimal_order_mapping_round_trips_through_phase1_constructor() -> None:
    order = Order.received(id=ORDER_ID)

    row = order_to_model(order, CREATED_AT)
    restored = order_from_models(row, [], [])

    assert restored == order
    assert row.created_at == CREATED_AT
    assert row.state == "RECEIVED"
    assert row.failure_origin is None


def test_populated_order_mapping_preserves_types_values_and_positions() -> None:
    line = OrderLine(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        sku="SKU-1",
        description="A widget",
        quantity=Decimal("5.00"),
        submitted_price=Decimal("10.50"),
        trusted_catalogue_price=Decimal("11.00"),
    )
    document = SourceDocument(
        id=UUID("33333333-3333-4333-8333-333333333333"),
        document_type=SourceDocumentType.EMAIL_BODY,
        name="order email",
        mime_type="message/rfc822",
        sha256="a" * 64,
        message_id="message-1",
        storage_reference="mailbox/message-1",
        metadata=(
            ("message_source", "email"),
            ("message_source", "archive"),
            ("mailbox", "orders"),
        ),
    )
    order = Order.received(
        id=ORDER_ID,
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2026, 9, 14),
        requested_delivery_date=date(2026, 10, 1),
        currency="USD",
        lines=(line,),
        source_documents=(document,),
    )

    line_row = line_to_model(order.id, 0, line)
    document_row = source_document_to_model(order.id, 0, document)
    restored = order_from_models(
        order_to_model(order, CREATED_AT),
        [line_row],
        [document_row],
    )

    assert restored == order
    assert restored.lines[0].quantity == Decimal("5.00")
    assert isinstance(restored.lines[0].quantity, Decimal)
    assert restored.lines[0].submitted_price == Decimal("10.50")
    assert restored.source_documents[0].metadata == document.metadata
    assert document_row.metadata_ == [
        ["message_source", "email"],
        ["message_source", "archive"],
        ["mailbox", "orders"],
    ]


def test_child_mapping_preserves_explicit_positions_and_ordered_metadata() -> None:
    first = OrderLine(
        id=uuid4(),
        sku="FIRST",
        description=None,
        quantity=Decimal("1"),
        submitted_price=None,
        trusted_catalogue_price=None,
    )
    second = OrderLine(
        id=uuid4(),
        sku="SECOND",
        description=None,
        quantity=Decimal("2"),
        submitted_price=None,
        trusted_catalogue_price=None,
    )
    order = Order.received(id=ORDER_ID, lines=(first, second))

    restored = order_from_models(
        order_to_model(order, CREATED_AT),
        [line_to_model(ORDER_ID, 1, second), line_to_model(ORDER_ID, 0, first)],
        [],
    )

    assert restored.lines == (first, second)
    assert [line.id for line in restored.lines] == [first.id, second.id]


def test_validation_issue_and_audit_event_map_as_separate_phase1_records() -> None:
    issue_row = ValidationIssueModel(
        order_id=ORDER_ID,
        position=0,
        rule_code="REQUIRED_PO",
        severity="WARNING",
        field="po_number",
        expected="present",
        actual=None,
        explanation="The purchase-order number is missing.",
    )
    audit = AuditEvent(
        id=UUID("44444444-4444-4444-8444-444444444444"),
        order_id=ORDER_ID,
        event_type="ORDER_RECEIVED",
        actor="system",
        occurred_at=CREATED_AT,
        description="Order received through API intake.",
    )
    audit_row = AuditEventModel(
        id=audit.id,
        order_id=audit.order_id,
        event_type=audit.event_type,
        actor=audit.actor,
        occurred_at=audit.occurred_at,
        description=audit.description,
    )

    issue = validation_issue_from_model(issue_row)
    restored_audit = audit_event_from_model(audit_row)

    assert issue == ValidationIssue(
        rule_code="REQUIRED_PO",
        severity=ValidationSeverity.WARNING,
        field="po_number",
        expected="present",
        actual=None,
        explanation="The purchase-order number is missing.",
    )
    assert restored_audit == audit
    assert restored_audit.occurred_at.tzinfo is not None
    assert restored_audit.occurred_at.utcoffset() is not None


def test_malformed_persisted_state_and_metadata_are_rejected() -> None:
    order_row = order_to_model(Order.received(id=ORDER_ID), CREATED_AT)
    order_row.state = "NOT_A_STATE"
    with pytest.raises(DomainValidationError):
        order_from_models(order_row, [], [])

    failed_order_row = order_to_model(Order.received(id=ORDER_ID), CREATED_AT)
    failed_order_row.state = "FAILED_FINAL"
    with pytest.raises(DomainValidationError):
        order_from_models(failed_order_row, [], [])

    document_row = SourceDocumentModel(
        id=uuid4(),
        order_id=ORDER_ID,
        position=0,
        document_type="FORM",
        name="form",
        mime_type="application/json",
        sha256="b" * 64,
        metadata=[["only-one-value"]],
    )
    with pytest.raises(DomainValidationError):
        source_document_from_model(document_row)


def test_float_numeric_storage_is_rejected_instead_of_converted() -> None:
    order = Order.received(id=ORDER_ID)
    line_row = line_to_model(
        ORDER_ID,
        0,
        OrderLine(
            id=uuid4(),
            sku="SKU",
            description=None,
            quantity=Decimal("1.25"),
            submitted_price=None,
            trusted_catalogue_price=None,
        ),
    )
    line_row.quantity = 1.25  # type: ignore[assignment]

    with pytest.raises(DomainValidationError):
        order_from_models(order_to_model(order, CREATED_AT), [line_row], [])
