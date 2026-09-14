"""Unit tests for the Phase 2 transport schemas and explicit mappings."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from opsflow.api.schemas import (
    AuditEventResponse,
    AuditListResponse,
    OrderCreateRequest,
    OrderDetailResponse,
    OrderListResponse,
    OrderSummaryResponse,
    order_detail_response,
    to_create_order_input,
)
from opsflow.application.orders import CreateOrderInput
from opsflow.domain import (
    AuditEvent,
    Order,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.persistence.repositories import OrderSummary, PersistedOrder


def _minimal_payload() -> dict[str, object]:
    return {}


def _populated_payload() -> dict[str, object]:
    return {
        "customer_reference": "CUST-1",
        "po_number": "PO-1",
        "order_date": "2030-01-02",
        "requested_delivery_date": "2030-01-10",
        "currency": "USD",
        "lines": [
            {
                "sku": "SKU-1",
                "description": "Widget",
                "quantity": "2.50",
                "submitted_price": "10.00",
                "trusted_catalogue_price": "11.00",
            }
        ],
        "source_documents": [
            {
                "document_type": "FORM",
                "name": "intake-form",
                "mime_type": "application/json",
                "sha256": "a" * 64,
                "message_id": "message-1",
                "storage_reference": "synthetic://form/1",
                "metadata": [
                    {"key": "source", "value": "form"},
                    {"key": "source", "value": "archive"},
                ],
            }
        ],
    }


def test_minimal_request_parses_with_empty_collections() -> None:
    request = OrderCreateRequest.model_validate(_minimal_payload())

    assert request.lines == []
    assert request.source_documents == []
    assert to_create_order_input(request) == CreateOrderInput()


def test_populated_request_parses_decimal_dates_enum_and_metadata() -> None:
    request = OrderCreateRequest.model_validate(_populated_payload())

    assert request.order_date == date(2030, 1, 2)
    assert request.lines[0].quantity == Decimal("2.50")
    assert isinstance(request.lines[0].quantity, Decimal)
    assert request.source_documents[0].document_type is SourceDocumentType.FORM
    assert [pair.model_dump() for pair in request.source_documents[0].metadata] == [
        {"key": "source", "value": "form"},
        {"key": "source", "value": "archive"},
    ]


def test_request_maps_losslessly_to_create_order_input() -> None:
    request = OrderCreateRequest.model_validate(_populated_payload())
    mapped = to_create_order_input(request)

    assert isinstance(mapped, CreateOrderInput)
    assert mapped.customer_reference == "CUST-1"
    assert mapped.order_date == date(2030, 1, 2)
    assert mapped.lines[0].quantity == Decimal("2.50")
    assert mapped.source_documents[0].metadata == (
        ("source", "form"),
        ("source", "archive"),
    )


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "state",
        "failure_origin",
        "created_at",
        "validation_issues",
        "audit_events",
    ],
)
def test_request_rejects_server_owned_top_level_fields(field: str) -> None:
    payload = _minimal_payload()
    payload[field] = "server-owned"

    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(payload)


def test_request_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"unexpected": True})


def test_request_rejects_unknown_nested_line_field() -> None:
    payload = {"lines": [{"quantity": "1", "sku": "SKU-1", "line_id": "nope"}]}

    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(payload)


def test_request_rejects_line_id() -> None:
    payload = {"lines": [{"quantity": "1", "sku": "SKU-1", "id": str(UUID(int=1))}]}

    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(payload)


def test_request_rejects_unknown_nested_document_field() -> None:
    payload = {
        "source_documents": [
            {
                "document_type": "FORM",
                "name": "form",
                "mime_type": "application/json",
                "sha256": "a" * 64,
                "document_id": "nope",
            }
        ]
    }

    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(payload)


def test_request_rejects_source_document_id() -> None:
    payload = {
        "source_documents": [
            {
                "document_type": "FORM",
                "name": "form",
                "mime_type": "application/json",
                "sha256": "a" * 64,
                "id": str(UUID(int=1)),
            }
        ]
    }

    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(payload)


def test_request_rejects_unknown_metadata_pair_field() -> None:
    payload = {"source_documents": [{"metadata": [{"key": "source", "extra": "nope"}]}]}

    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(payload)


def test_duplicate_metadata_keys_and_order_are_preserved() -> None:
    request = OrderCreateRequest.model_validate(_populated_payload())
    mapped = to_create_order_input(request)

    assert mapped.source_documents[0].metadata == (
        ("source", "form"),
        ("source", "archive"),
    )


def test_response_detail_contains_domain_data_metadata_and_validation_issues() -> None:
    order = _domain_order()
    created_at = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    issue = ValidationIssue(
        rule_code="RULE-1",
        severity=ValidationSeverity.WARNING,
        field="currency",
        expected="USD",
        actual="EUR",
        explanation="Synthetic issue",
    )

    response = order_detail_response(PersistedOrder(order, created_at, (issue,)))
    payload = response.model_dump(mode="json")

    assert isinstance(response, OrderDetailResponse)
    assert payload["id"] == str(order.id)
    assert payload["state"] == "RECEIVED"
    assert payload["created_at"] == "2030-01-01T12:00:00Z"
    assert payload["lines"][0]["id"] == str(order.lines[0].id)
    assert payload["source_documents"][0]["metadata"] == [
        {"key": "source", "value": "form"},
        {"key": "source", "value": "archive"},
    ]
    assert payload["validation_issues"][0]["rule_code"] == "RULE-1"
    assert "audit_events" not in OrderDetailResponse.model_fields


def test_summary_response_excludes_children_and_audit() -> None:
    summary = OrderSummary(
        id=UUID(int=1),
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2030, 1, 2),
        requested_delivery_date=None,
        currency="USD",
        state=Order.received(id=UUID(int=1)).state,
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    response = OrderSummaryResponse(
        id=summary.id,
        customer_reference=summary.customer_reference,
        po_number=summary.po_number,
        order_date=summary.order_date,
        requested_delivery_date=summary.requested_delivery_date,
        currency=summary.currency,
        state=summary.state,
        created_at=summary.created_at,
    )

    assert response.model_dump(mode="json")["state"] == "RECEIVED"
    assert "lines" not in OrderSummaryResponse.model_fields
    assert "source_documents" not in OrderSummaryResponse.model_fields
    assert "validation_issues" not in OrderSummaryResponse.model_fields
    assert "audit_events" not in OrderSummaryResponse.model_fields


def test_order_list_response_has_only_pagination_and_summary_items() -> None:
    response = OrderListResponse(items=[], limit=50, offset=0, total=137)

    assert response.model_dump() == {"items": [], "limit": 50, "offset": 0, "total": 137}


def test_audit_response_is_separate_and_preserves_timezone() -> None:
    occurred_at = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    event = AuditEvent(
        id=UUID(int=2),
        order_id=UUID(int=1),
        event_type="ORDER_RECEIVED",
        actor="system",
        occurred_at=occurred_at,
        description="Order received through API intake.",
    )
    response = AuditListResponse(
        items=(
            AuditEventResponse(
                id=event.id,
                order_id=event.order_id,
                event_type=event.event_type,
                actor=event.actor,
                occurred_at=event.occurred_at,
                description=event.description,
            ),
        )
    )

    assert response.items[0].occurred_at == occurred_at
    assert "audit_events" not in OrderDetailResponse.model_fields


def _domain_order() -> Order:
    return Order.received(
        id=UUID(int=1),
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2030, 1, 2),
        requested_delivery_date=date(2030, 1, 10),
        currency="USD",
        lines=(
            OrderLine(
                id=UUID(int=3),
                sku="SKU-1",
                description="Widget",
                quantity=Decimal("2.50"),
                submitted_price=Decimal("10.00"),
                trusted_catalogue_price=Decimal("11.00"),
            ),
        ),
        source_documents=(
            SourceDocument(
                id=UUID(int=4),
                document_type=SourceDocumentType.FORM,
                name="intake-form",
                mime_type="application/json",
                sha256="a" * 64,
                message_id=None,
                storage_reference="synthetic://form/1",
                metadata=(("source", "form"), ("source", "archive")),
            ),
        ),
    )
