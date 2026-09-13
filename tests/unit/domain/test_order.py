from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from opsflow.domain import (
    DomainValidationError,
    Order,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
)
from opsflow.domain.order import OrderState

ORDER_ID = UUID(int=10)
LINE_ID = UUID(int=11)
DOCUMENT_ID = UUID(int=12)
SHA256 = "a" * 64


def make_line() -> OrderLine:
    return OrderLine(LINE_ID, "SKU-001", "Widget", Decimal("2"), Decimal("10.00"), None)


def make_document() -> SourceDocument:
    return SourceDocument(
        DOCUMENT_ID,
        SourceDocumentType.PDF,
        "purchase-order.pdf",
        "application/pdf",
        SHA256,
        None,
        None,
        (),
    )


def test_order_state_has_exact_approved_values() -> None:
    assert [member.name for member in OrderState] == [
        "RECEIVED",
        "PROCESSING",
        "EXTRACTED",
        "VALIDATED",
        "NEEDS_REVIEW",
        "READY_FOR_APPROVAL",
        "APPROVED",
        "SYNCING",
        "COMPLETED",
        "REJECTED",
        "FAILED_RETRYABLE",
        "FAILED_FINAL",
    ]


def test_order_has_exact_approved_fields() -> None:
    assert [field.name for field in fields(Order)] == [
        "id",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "lines",
        "source_documents",
        "state",
        "failure_origin",
    ]


def test_received_factory_creates_minimal_pre_extraction_order() -> None:
    order = Order.received(id=ORDER_ID)

    assert order.id == ORDER_ID
    assert order.state is OrderState.RECEIVED
    assert order.failure_origin is None
    assert order.customer_reference is None
    assert order.po_number is None
    assert order.order_date is None
    assert order.requested_delivery_date is None
    assert order.currency is None
    assert order.lines == ()
    assert order.source_documents == ()


def test_received_factory_populates_optional_business_fields() -> None:
    line = make_line()
    document = make_document()

    order = Order.received(
        id=ORDER_ID,
        customer_reference="CUST-001",
        po_number="PO-001",
        order_date=date(2026, 9, 13),
        requested_delivery_date=date(2026, 10, 1),
        currency="ZZZ",
        lines=(line,),
        source_documents=(document,),
    )

    assert order.customer_reference == "CUST-001"
    assert order.po_number == "PO-001"
    assert order.order_date == date(2026, 9, 13)
    assert order.requested_delivery_date == date(2026, 10, 1)
    assert order.currency == "ZZZ"
    assert order.lines == (line,)
    assert order.source_documents == (document,)


def test_order_rejects_non_uuid_id() -> None:
    with pytest.raises(DomainValidationError):
        Order(id="not-a-uuid")  # type: ignore[arg-type]


def test_order_accepts_empty_tuple_collections() -> None:
    order = Order(id=ORDER_ID)

    assert order.lines == ()
    assert order.source_documents == ()


def test_order_accepts_valid_tuple_collections() -> None:
    line = make_line()
    document = make_document()
    order = Order(id=ORDER_ID, lines=(line,), source_documents=(document,))

    assert order.lines == (line,)
    assert order.source_documents == (document,)


@pytest.mark.parametrize("field", ["lines", "source_documents"])
def test_order_rejects_mutable_list_collections(field: str) -> None:
    with pytest.raises(DomainValidationError):
        Order(id=ORDER_ID, **{field: []})


@pytest.mark.parametrize(
    ("field", "value"),
    [("lines", (object(),)), ("source_documents", (object(),))],
)
def test_order_rejects_wrong_collection_element_types(field: str, value: tuple[object]) -> None:
    with pytest.raises(DomainValidationError):
        Order(id=ORDER_ID, **{field: value})


def test_order_is_frozen() -> None:
    order = Order.received(id=ORDER_ID)

    with pytest.raises(FrozenInstanceError):
        order.state = OrderState.PROCESSING  # type: ignore[misc]


@pytest.mark.parametrize("currency", ["USD", "EUR", "EGP", "ZZZ"])
def test_order_accepts_structurally_valid_currency(currency: str) -> None:
    order = Order(id=ORDER_ID, currency=currency)

    assert order.currency == currency


@pytest.mark.parametrize("currency", ["usd", "US", "USDD", "12A", 123])
def test_order_rejects_invalid_currency_shape(currency: object) -> None:
    with pytest.raises(DomainValidationError):
        Order(id=ORDER_ID, currency=currency)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("customer_reference", 1),
        ("po_number", 1),
        ("order_date", datetime(2026, 9, 13)),
        ("requested_delivery_date", datetime(2026, 10, 1)),
        ("state", "RECEIVED"),
        ("failure_origin", "PROCESSING"),
    ],
)
def test_order_rejects_wrong_structural_field_types(field: str, value: object) -> None:
    with pytest.raises(DomainValidationError):
        Order(id=ORDER_ID, **{field: value})


@pytest.mark.parametrize(
    ("state", "failure_origin"),
    [
        (OrderState.FAILED_RETRYABLE, None),
        (OrderState.FAILED_FINAL, OrderState.COMPLETED),
        (OrderState.RECEIVED, OrderState.SYNCING),
        (OrderState.COMPLETED, OrderState.PROCESSING),
    ],
)
def test_order_rejects_inconsistent_state_and_failure_origin(
    state: OrderState, failure_origin: OrderState | None
) -> None:
    with pytest.raises(DomainValidationError):
        Order(id=ORDER_ID, state=state, failure_origin=failure_origin)


@pytest.mark.parametrize("state", [OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL])
@pytest.mark.parametrize(
    "failure_origin",
    [OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.SYNCING],
)
def test_order_accepts_valid_failure_snapshots(
    state: OrderState, failure_origin: OrderState
) -> None:
    order = Order(id=ORDER_ID, state=state, failure_origin=failure_origin)

    assert order.state is state
    assert order.failure_origin is failure_origin


@pytest.mark.parametrize(
    "state",
    [
        OrderState.RECEIVED,
        OrderState.PROCESSING,
        OrderState.EXTRACTED,
        OrderState.VALIDATED,
        OrderState.NEEDS_REVIEW,
        OrderState.READY_FOR_APPROVAL,
        OrderState.APPROVED,
        OrderState.SYNCING,
        OrderState.COMPLETED,
        OrderState.REJECTED,
    ],
)
@pytest.mark.parametrize(
    "failure_origin",
    [OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.SYNCING],
)
def test_non_failure_states_reject_failure_origin(
    state: OrderState, failure_origin: OrderState
) -> None:
    with pytest.raises(DomainValidationError):
        Order(id=ORDER_ID, state=state, failure_origin=failure_origin)
