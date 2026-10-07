"""M10C transport resource and decimal-budget regression tests."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from opsflow.api.review_schemas import ReviewDraftRequest, ReviewRejectRequest
from opsflow.api.schemas import OrderCreateRequest


def _line(*, quantity: str = "1", submitted_price: str = "0") -> dict[str, str]:
    return {
        "sku": "SKU-1",
        "description": "line",
        "quantity": quantity,
        "submitted_price": submitted_price,
    }


def _document(
    *,
    metadata: list[dict[str, str]] | None = None,
    name: str = "source.csv",
    **overrides: str,
) -> dict[str, object]:
    return {
        "document_type": "CSV",
        "name": name,
        "mime_type": "text/csv",
        "sha256": "a" * 64,
        "metadata": metadata or [],
        **overrides,
    }


def _review_line(*, quantity: str = "1", submitted_price: str = "0") -> dict[str, str]:
    return {
        "sku": "SKU-1",
        "description": "line",
        "quantity": quantity,
        "submitted_price": submitted_price,
    }


def _review_payload(*, lines: list[dict[str, str]] | None = None) -> dict[str, object]:
    return {
        "customer_name": "Customer",
        "customer_reference": "CUST-1",
        "po_number": "PO-1",
        "order_date": None,
        "requested_delivery_date": None,
        "currency": "USD",
        "lines": lines if lines is not None else [_review_line()],
    }


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("customer_reference", 256),
        ("po_number", 256),
    ],
)
def test_core_string_boundaries_are_exact(field: str, limit: int) -> None:
    accepted = OrderCreateRequest.model_validate({field: "x" * limit})
    assert getattr(accepted, field) == "x" * limit
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({field: "x" * (limit + 1)})


@pytest.mark.parametrize(
    ("field", "limit"),
    [("sku", 256), ("description", 2_048)],
)
def test_core_line_string_boundaries_are_exact(field: str, limit: int) -> None:
    accepted = OrderCreateRequest.model_validate({"lines": [{**_line(), field: "x" * limit}]})
    assert getattr(accepted.lines[0], field) == "x" * limit
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"lines": [{**_line(), field: "x" * (limit + 1)}]})


@pytest.mark.parametrize(
    ("field", "limit"),
    [("name", 255), ("mime_type", 128), ("message_id", 256), ("storage_reference", 2_048)],
)
def test_core_source_document_string_boundaries_are_exact(field: str, limit: int) -> None:
    accepted = OrderCreateRequest.model_validate(
        {"source_documents": [_document(**{field: "x" * limit})]}
    )
    assert getattr(accepted.source_documents[0], field) == "x" * limit
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(
            {"source_documents": [_document(**{field: "x" * (limit + 1)})]}
        )


def test_core_collection_boundaries_are_exact() -> None:
    OrderCreateRequest.model_validate({"lines": [_line() for _ in range(200)]})
    OrderCreateRequest.model_validate({"source_documents": [_document() for _ in range(8)]})
    OrderCreateRequest.model_validate(
        {"source_documents": [_document(metadata=[{"key": "k", "value": "v"} for _ in range(32)])]}
    )
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"lines": [_line() for _ in range(201)]})
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"source_documents": [_document() for _ in range(9)]})
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate(
            {
                "source_documents": [
                    _document(metadata=[{"key": "k", "value": "v"} for _ in range(33)])
                ]
            }
        )


@pytest.mark.parametrize("field", ["key", "value"])
def test_metadata_string_boundaries_are_exact(field: str) -> None:
    limit = 128 if field == "key" else 512
    document = _document(metadata=[{field: "x" * limit, "value" if field == "key" else "key": "v"}])
    if field == "value":
        document = _document(metadata=[{"key": "k", "value": "x" * limit}])
    OrderCreateRequest.model_validate({"source_documents": [document]})
    invalid = {"key": "k", "value": "v"}
    invalid[field] = "x" * (limit + 1)
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"source_documents": [_document(metadata=[invalid])]})


@pytest.mark.parametrize("value", ["9" * 28, "1.12345678", "1E+20"])
def test_core_decimal_budget_accepts_valid_boundaries(value: str) -> None:
    request = OrderCreateRequest.model_validate(
        {"lines": [_line(quantity=value, submitted_price=value)]}
    )
    assert request.lines[0].quantity == Decimal(value)


@pytest.mark.parametrize(
    "value",
    [
        "9" * 29,
        "1.123456789",
        "1E+28",
        "1E+100",
        "1E-9",
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_core_decimal_budget_rejects_overflow_precision_scale_and_non_finite(value: str) -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"lines": [_line(quantity=value)]})


@pytest.mark.parametrize("value", ["0", "-1"])
def test_core_quantity_remains_positive(value: str) -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"lines": [_line(quantity=value)]})


def test_core_price_remains_non_negative() -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"lines": [_line(submitted_price="-0.01")]})


def test_review_line_count_and_decimal_caps_match_core_transport() -> None:
    ReviewDraftRequest.model_validate(_review_payload(lines=[_review_line() for _ in range(200)]))
    with pytest.raises(ValidationError):
        ReviewDraftRequest.model_validate(
            _review_payload(lines=[_review_line() for _ in range(201)])
        )
    ReviewDraftRequest.model_validate(_review_payload(lines=[_review_line(quantity="9" * 28)]))
    with pytest.raises(ValidationError):
        ReviewDraftRequest.model_validate(_review_payload(lines=[_review_line(quantity="9" * 29)]))


def test_review_strings_and_rejection_reason_are_bounded() -> None:
    ReviewDraftRequest.model_validate(
        _review_payload()
        | {"customer_name": "x" * 255, "customer_reference": "x" * 256, "po_number": "x" * 256}
    )
    with pytest.raises(ValidationError):
        ReviewDraftRequest.model_validate(_review_payload() | {"customer_reference": "x" * 257})
    ReviewRejectRequest.model_validate({"reason": "x" * 500})
    with pytest.raises(ValidationError):
        ReviewRejectRequest.model_validate({"reason": "x" * 501})
