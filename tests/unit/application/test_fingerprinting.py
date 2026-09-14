"""Pure tests for semantic order inputs and canonical fingerprinting."""

import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from opsflow.application.orders import (
    CreateLineInput,
    CreateOrderInput,
    CreateSourceDocumentInput,
    canonical_order_request,
    fingerprint_order_request,
)
from opsflow.domain import DomainValidationError, SourceDocumentType


def _line(quantity: str = "5.00") -> CreateLineInput:
    return CreateLineInput(
        sku="SKU-1",
        description="Widget",
        quantity=Decimal(quantity),
        submitted_price=Decimal("10.00"),
        trusted_catalogue_price=Decimal("11.00"),
    )


def _document(metadata: tuple[tuple[str, str], ...] = ()) -> CreateSourceDocumentInput:
    return CreateSourceDocumentInput(
        document_type=SourceDocumentType.FORM,
        name="intake-form",
        mime_type="application/json",
        sha256="a" * 64,
        message_id=None,
        storage_reference="synthetic://form/1",
        metadata=metadata,
    )


def _request(
    *,
    quantity: str = "5.00",
    lines: tuple[CreateLineInput, ...] | None = None,
    source_documents: tuple[CreateSourceDocumentInput, ...] | None = None,
) -> CreateOrderInput:
    return CreateOrderInput(
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2030, 1, 2),
        requested_delivery_date=date(2030, 1, 10),
        currency="USD",
        lines=(_line(quantity),) if lines is None else lines,
        source_documents=() if source_documents is None else source_documents,
    )


def test_minimal_input_uses_empty_ordered_collections() -> None:
    request = CreateOrderInput()

    payload = json.loads(canonical_order_request(request))

    assert payload == {
        "currency": None,
        "customer_reference": None,
        "lines": [],
        "order_date": None,
        "po_number": None,
        "requested_delivery_date": None,
        "source_documents": [],
    }


def test_populated_input_contains_semantic_fields_only() -> None:
    request = _request(source_documents=(_document((("source", "form"),)),))

    payload = json.loads(canonical_order_request(request))

    assert payload["order_date"] == "2030-01-02"
    assert payload["lines"][0]["quantity"] == "5"
    assert payload["source_documents"][0]["document_type"] == "FORM"
    assert "id" not in payload
    assert "created_at" not in payload
    assert "state" not in payload
    assert "failure_origin" not in payload
    assert "id" not in payload["lines"][0]
    assert "id" not in payload["source_documents"][0]


@pytest.mark.parametrize("spelling", ["5", "5.0", "5.00"])
def test_equivalent_decimal_spellings_have_the_same_fingerprint(spelling: str) -> None:
    assert fingerprint_order_request(_request(quantity=spelling)) == fingerprint_order_request(
        _request(quantity="5")
    )


def test_decimal_exponents_and_trailing_zeroes_are_normalized() -> None:
    request = _request(quantity="1E+3")
    request_small = _request(quantity="0.00100")

    assert json.loads(canonical_order_request(request))["lines"][0]["quantity"] == "1000"
    assert json.loads(canonical_order_request(request_small))["lines"][0]["quantity"] == "0.001"


@pytest.mark.parametrize("spelling", ["0", "0.0", "-0", "-0.00"])
def test_all_zero_decimal_spellings_are_canonical_zero(spelling: str) -> None:
    request = replace(_request(), lines=(replace(_line("5"), quantity=Decimal(spelling)),))

    assert json.loads(canonical_order_request(request))["lines"][0]["quantity"] == "0"


def test_nested_member_order_does_not_change_canonical_bytes() -> None:
    request = _request(source_documents=(_document((("source", "form"),)),))
    expected = json.dumps(
        {
            "source_documents": [
                {
                    "storage_reference": "synthetic://form/1",
                    "sha256": "a" * 64,
                    "name": "intake-form",
                    "metadata": [["source", "form"]],
                    "mime_type": "application/json",
                    "message_id": None,
                    "document_type": "FORM",
                }
            ],
            "requested_delivery_date": "2030-01-10",
            "po_number": "PO-1",
            "order_date": "2030-01-02",
            "lines": [
                {
                    "trusted_catalogue_price": "11",
                    "submitted_price": "10",
                    "sku": "SKU-1",
                    "quantity": "5",
                    "description": "Widget",
                }
            ],
            "currency": "USD",
            "customer_reference": "CUST-1",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    assert canonical_order_request(request) == expected


def test_semantic_line_order_is_significant() -> None:
    first = _line("1")
    second = replace(_line("2"), sku="SKU-2")

    assert fingerprint_order_request(_request(lines=(first, second))) != fingerprint_order_request(
        _request(lines=(second, first))
    )


def test_semantic_source_document_order_is_significant() -> None:
    first = _document((("source", "first"),))
    second = replace(_document((("source", "second"),)), name="second")

    assert fingerprint_order_request(
        _request(source_documents=(first, second))
    ) != fingerprint_order_request(_request(source_documents=(second, first)))


def test_metadata_pair_order_and_duplicate_keys_are_preserved() -> None:
    request = _request(source_documents=(_document((("source", "archive"), ("source", "email"))),))

    payload = json.loads(canonical_order_request(request))

    assert payload["source_documents"][0]["metadata"] == [
        ["source", "archive"],
        ["source", "email"],
    ]
    reordered = _request(
        source_documents=(_document((("source", "email"), ("source", "archive"))),)
    )
    assert fingerprint_order_request(request) != fingerprint_order_request(reordered)


def test_dates_and_enums_use_stable_wire_values() -> None:
    payload = json.loads(canonical_order_request(_request(source_documents=(_document(),))))

    assert payload["order_date"] == "2030-01-02"
    assert payload["requested_delivery_date"] == "2030-01-10"
    assert payload["source_documents"][0]["document_type"] == "FORM"


def test_fingerprint_is_lowercase_sha256_hex() -> None:
    request = _request()
    canonical = canonical_order_request(request)

    assert fingerprint_order_request(request) == hashlib.sha256(canonical).hexdigest()
    assert len(fingerprint_order_request(request)) == 64
    assert fingerprint_order_request(request).islower()
    assert all(character in "0123456789abcdef" for character in fingerprint_order_request(request))


@pytest.mark.parametrize(
    "value", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_non_finite_decimal_values_are_rejected(value: Decimal) -> None:
    request = replace(_request(), lines=(replace(_line("5"), quantity=value),))

    with pytest.raises(DomainValidationError):
        canonical_order_request(request)


def test_create_input_records_do_not_generate_server_ids() -> None:
    request = _request()

    assert not hasattr(request, "id")
    assert not hasattr(request.lines[0], "id")
    assert not hasattr(request, "state")
