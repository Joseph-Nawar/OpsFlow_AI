from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from opsflow.domain import (
    DomainValidationError,
    InvalidStateTransitionError,
    Order,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
)
from opsflow.domain.order import OrderState
from opsflow.validation import ValidatedOrderData, ValidatedOrderLine

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


def make_extracted_order() -> Order:
    return Order(
        id=ORDER_ID,
        customer_reference="EXTRACTED-CUSTOMER",
        po_number="EXTRACTED-PO",
        order_date=date(2026, 9, 1),
        requested_delivery_date=date(2026, 9, 15),
        currency="USD",
        lines=(make_line(),),
        source_documents=(make_document(),),
        state=OrderState.EXTRACTED,
    )


def make_validated_data() -> ValidatedOrderData:
    return ValidatedOrderData(
        customer_reference="TRUSTED-CUSTOMER",
        po_number="TRUSTED-PO",
        order_date=date(2026, 9, 2),
        requested_delivery_date=date(2026, 9, 20),
        currency="EUR",
        lines=(
            ValidatedOrderLine(
                sku="TRUSTED-001",
                description="Trusted widget",
                quantity=Decimal("3"),
                submitted_price=Decimal("11.25"),
                trusted_catalogue_price=Decimal("12.00"),
            ),
            ValidatedOrderLine(
                sku="TRUSTED-002",
                description=None,
                quantity=Decimal("1.5"),
                submitted_price=Decimal("4"),
                trusted_catalogue_price=Decimal("4.50"),
            ),
        ),
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


def test_promote_validated_data_replaces_trusted_snapshot_without_transitioning() -> None:
    original = make_extracted_order()
    data = make_validated_data()
    line_ids = (UUID(int=101), UUID(int=102))

    promoted = original.promote_validated_data(data, line_ids)

    assert promoted is not original
    assert promoted.id == original.id
    assert promoted.state is OrderState.EXTRACTED
    assert promoted.failure_origin is None
    assert promoted.source_documents == original.source_documents
    assert promoted.customer_reference == data.customer_reference
    assert promoted.po_number == data.po_number
    assert promoted.order_date == data.order_date
    assert promoted.requested_delivery_date == data.requested_delivery_date
    assert promoted.currency == data.currency
    assert promoted.lines == (
        OrderLine(
            id=line_ids[0],
            sku="TRUSTED-001",
            description="Trusted widget",
            quantity=Decimal("3"),
            submitted_price=Decimal("11.25"),
            trusted_catalogue_price=Decimal("12.00"),
        ),
        OrderLine(
            id=line_ids[1],
            sku="TRUSTED-002",
            description=None,
            quantity=Decimal("1.5"),
            submitted_price=Decimal("4"),
            trusted_catalogue_price=Decimal("4.50"),
        ),
    )
    assert original.customer_reference == "EXTRACTED-CUSTOMER"
    assert original.lines == (make_line(),)


@pytest.mark.parametrize(
    "state", [state for state in OrderState if state is not OrderState.EXTRACTED]
)
def test_promote_validated_data_requires_extracted_state(state: OrderState) -> None:
    order = Order(
        id=ORDER_ID,
        state=state,
        failure_origin=(
            OrderState.PROCESSING
            if state in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL)
            else None
        ),
    )

    with pytest.raises(InvalidStateTransitionError) as error:
        order.promote_validated_data(make_validated_data(), (UUID(int=101), UUID(int=102)))
    assert error.value.current_state is state
    assert error.value.operation == "promote_validated_data"


def test_promote_reviewed_data_replaces_trusted_snapshot_without_transitioning() -> None:
    original = replace(make_extracted_order(), state=OrderState.NEEDS_REVIEW)
    data = make_validated_data()
    line_ids = (UUID(int=201), UUID(int=202))

    promoted = original.promote_reviewed_data(data, line_ids)

    assert promoted is not original
    assert promoted.id == original.id
    assert promoted.state is OrderState.NEEDS_REVIEW
    assert promoted.failure_origin is None
    assert promoted.source_documents == original.source_documents
    assert promoted.customer_reference == data.customer_reference
    assert promoted.po_number == data.po_number
    assert promoted.order_date == data.order_date
    assert promoted.requested_delivery_date == data.requested_delivery_date
    assert promoted.currency == data.currency
    assert promoted.lines == (
        OrderLine(
            id=line_ids[0],
            sku="TRUSTED-001",
            description="Trusted widget",
            quantity=Decimal("3"),
            submitted_price=Decimal("11.25"),
            trusted_catalogue_price=Decimal("12.00"),
        ),
        OrderLine(
            id=line_ids[1],
            sku="TRUSTED-002",
            description=None,
            quantity=Decimal("1.5"),
            submitted_price=Decimal("4"),
            trusted_catalogue_price=Decimal("4.50"),
        ),
    )
    assert original.customer_reference == "EXTRACTED-CUSTOMER"
    assert original.lines == (make_line(),)


@pytest.mark.parametrize(
    "state", [state for state in OrderState if state is not OrderState.NEEDS_REVIEW]
)
def test_promote_reviewed_data_requires_needs_review_state(state: OrderState) -> None:
    order = Order(
        id=ORDER_ID,
        state=state,
        failure_origin=(
            OrderState.PROCESSING
            if state in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL)
            else None
        ),
    )

    with pytest.raises(InvalidStateTransitionError) as error:
        order.promote_reviewed_data(make_validated_data(), (UUID(int=201), UUID(int=202)))
    assert error.value.current_state is state
    assert error.value.operation == "promote_reviewed_data"


@pytest.mark.parametrize(
    "line_ids", [(UUID(int=201),), (UUID(int=201), UUID(int=202), UUID(int=203))]
)
def test_promote_reviewed_data_requires_exact_line_id_count(
    line_ids: tuple[UUID, ...],
) -> None:
    order = replace(make_extracted_order(), state=OrderState.NEEDS_REVIEW)

    with pytest.raises(DomainValidationError):
        order.promote_reviewed_data(make_validated_data(), line_ids)


def test_promote_reviewed_data_requires_immutable_uuid_ids() -> None:
    order = replace(make_extracted_order(), state=OrderState.NEEDS_REVIEW)
    data = make_validated_data()

    with pytest.raises(DomainValidationError):
        order.promote_reviewed_data(data, [UUID(int=201), UUID(int=202)])  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        order.promote_reviewed_data(
            data,
            (UUID(int=201), "not-a-uuid"),  # type: ignore[arg-type]
        )


def test_promote_reviewed_data_accepts_only_validated_order_data() -> None:
    order = replace(make_extracted_order(), state=OrderState.NEEDS_REVIEW)

    with pytest.raises(DomainValidationError):
        order.promote_reviewed_data(object(), (UUID(int=201), UUID(int=202)))  # type: ignore[arg-type]


def test_promote_reviewed_data_revalidates_phase_one_line_invariants() -> None:
    order = replace(make_extracted_order(), state=OrderState.NEEDS_REVIEW)
    data = make_validated_data()
    object.__setattr__(data.lines[0], "quantity", Decimal("0"))

    with pytest.raises(DomainValidationError, match="quantity must be greater than zero"):
        order.promote_reviewed_data(data, (UUID(int=201), UUID(int=202)))


@pytest.mark.parametrize(
    "line_ids", [(UUID(int=101),), (UUID(int=101), UUID(int=102), UUID(int=103))]
)
def test_promote_validated_data_requires_exact_line_id_count(line_ids: tuple[UUID, ...]) -> None:
    with pytest.raises(DomainValidationError):
        make_extracted_order().promote_validated_data(make_validated_data(), line_ids)


def test_promote_validated_data_requires_tuple_of_uuids() -> None:
    order = make_extracted_order()
    data = make_validated_data()

    with pytest.raises(DomainValidationError):
        order.promote_validated_data(data, [UUID(int=101), UUID(int=102)])  # type: ignore[arg-type]
    with pytest.raises(DomainValidationError):
        order.promote_validated_data(data, (UUID(int=101), "not-a-uuid"))  # type: ignore[arg-type]


def test_promote_validated_data_accepts_only_validated_order_data() -> None:
    with pytest.raises(DomainValidationError):
        make_extracted_order().promote_validated_data(object(), (UUID(int=101), UUID(int=102)))  # type: ignore[arg-type]


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
