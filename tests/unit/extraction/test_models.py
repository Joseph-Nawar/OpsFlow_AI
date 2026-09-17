from dataclasses import FrozenInstanceError, fields
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from opsflow.domain.records import SourceDocumentType
from opsflow.extraction.errors import (
    ExtractionError,
    ExtractionResponseError,
    ProviderError,
    ProviderTimeoutError,
)
from opsflow.extraction.models import (
    Evidence,
    ExtractedLine,
    ExtractionDraft,
    ProviderEvidenceResponse,
    ProviderExtractionResponse,
    ProviderLineResponse,
    build_provider_response_schema,
)


def _provider_payload() -> dict[str, object]:
    return {
        "customer_name": "Synthetic Buyer",
        "customer_reference": "CUST-1",
        "po_number": "PO-1",
        "order_date": "2026-09-17",
        "requested_delivery_date": None,
        "currency": "XYZ",
        "lines": [
            {
                "sku": "SKU-1",
                "description": "Synthetic widget",
                "quantity": "-3",
                "submitted_price": "0E+2",
            }
        ],
        "notes": None,
        "evidence": [
            {
                "field_path": "po_number",
                "source_location": "text:body",
                "quote": "PO-1",
            }
        ],
    }


def _draft() -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.EMAIL_BODY,
        customer_name="Synthetic Buyer",
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2026, 9, 17),
        requested_delivery_date=None,
        currency="XYZ",
        lines=(
            ExtractedLine(
                sku=None,
                description=None,
                quantity=Decimal("-3"),
                submitted_price=Decimal("0"),
            ),
        ),
        notes=None,
        evidence=(Evidence("po_number", "text:body", "PO-1"),),
    )


def test_provider_response_accepts_required_nullable_fields_and_strict_strings() -> None:
    response = ProviderExtractionResponse.model_validate(_provider_payload(), strict=True)

    assert response.lines[0].quantity == "-3"
    assert response.lines[0].submitted_price == "0E+2"
    assert response.requested_delivery_date is None


@pytest.mark.parametrize(
    "missing_key",
    [
        "customer_name",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "lines",
        "notes",
        "evidence",
    ],
)
def test_provider_response_requires_every_top_level_key(missing_key: str) -> None:
    payload = _provider_payload()
    del payload[missing_key]

    with pytest.raises(ValidationError):
        ProviderExtractionResponse.model_validate(payload, strict=True)


@pytest.mark.parametrize("nullable_key", ["customer_name", "po_number", "order_date", "notes"])
def test_provider_response_keeps_nullable_keys_required(nullable_key: str) -> None:
    payload = _provider_payload()
    payload[nullable_key] = None

    response = ProviderExtractionResponse.model_validate(payload, strict=True)

    assert getattr(response, nullable_key) is None


@pytest.mark.parametrize("extra_location", ["top-level", "line", "evidence"])
def test_provider_response_forbids_extra_fields_at_every_object_level(
    extra_location: str,
) -> None:
    payload = _provider_payload()
    if extra_location == "top-level":
        payload["unexpected"] = "nope"
    elif extra_location == "line":
        line = payload["lines"][0]  # type: ignore[index]
        line["unexpected"] = "nope"  # type: ignore[index]
    else:
        evidence = payload["evidence"][0]  # type: ignore[index]
        evidence["unexpected"] = "nope"  # type: ignore[index]

    with pytest.raises(ValidationError):
        ProviderExtractionResponse.model_validate(payload, strict=True)


def test_provider_response_requires_all_line_and_evidence_keys() -> None:
    payload = _provider_payload()
    del payload["lines"][0]["quantity"]  # type: ignore[index]
    del payload["evidence"][0]["quote"]  # type: ignore[index]

    with pytest.raises(ValidationError):
        ProviderExtractionResponse.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("customer_name", 123),
        ("po_number", 1.5),
        ("currency", True),
    ],
)
def test_provider_response_rejects_non_string_scalar_coercion(
    field: str,
    value: object,
) -> None:
    payload = _provider_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        ProviderExtractionResponse.model_validate(payload, strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", 3),
        ("submitted_price", 2.5),
        ("quantity", False),
    ],
)
def test_provider_line_rejects_numeric_and_boolean_coercion(field: str, value: object) -> None:
    payload = _provider_payload()
    payload["lines"][0][field] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        ProviderExtractionResponse.model_validate(payload, strict=True)


@pytest.mark.parametrize("field", ["customer_name", "customer_reference", "po_number", "currency"])
def test_provider_response_rejects_blank_scalar_strings(field: str) -> None:
    payload = _provider_payload()
    payload[field] = " \t"

    with pytest.raises(ValidationError):
        ProviderExtractionResponse.model_validate(payload, strict=True)


def test_provider_line_and_evidence_reject_blank_strings() -> None:
    line = {
        "sku": " ",
        "description": "description",
        "quantity": "1",
        "submitted_price": None,
    }
    evidence = {"field_path": "po_number", "source_location": "text:body", "quote": " "}

    with pytest.raises(ValidationError):
        ProviderLineResponse.model_validate(line, strict=True)
    with pytest.raises(ValidationError):
        ProviderEvidenceResponse.model_validate(evidence, strict=True)


def test_provider_response_schema_is_strict_and_portable() -> None:
    schema = build_provider_response_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "customer_name",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "lines",
        "notes",
        "evidence",
    }
    assert schema["properties"]["lines"]["type"] == "array"  # type: ignore[index]
    assert schema["properties"]["evidence"]["type"] == "array"  # type: ignore[index]
    assert schema["$defs"]["ProviderLineResponse"]["additionalProperties"] is False  # type: ignore[index]
    assert schema["$defs"]["ProviderEvidenceResponse"]["additionalProperties"] is False  # type: ignore[index]


def test_final_records_are_frozen_slotted_and_preserve_extraction_values() -> None:
    line = ExtractedLine(None, None, Decimal("-3"), Decimal("0"))
    evidence = Evidence("po_number", "text:body", "PO-1")
    draft = _draft()

    for record in (line, evidence, draft):
        with pytest.raises(FrozenInstanceError):
            setattr(record, fields(record)[0].name, object())
        assert not hasattr(record, "__dict__")

    assert line.quantity == Decimal("-3")
    assert line.sku is None
    assert line.description is None
    assert draft.currency == "XYZ"


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_extracted_line_rejects_non_finite_decimals(value: Decimal) -> None:
    with pytest.raises(ValueError):
        ExtractedLine("SKU-1", "Widget", value, None)


def test_final_records_reject_invalid_sha256_and_mutable_collections() -> None:
    with pytest.raises(ValueError):
        ExtractionDraft(
            source_sha256="A" * 64,
            source_document_type=SourceDocumentType.EMAIL_BODY,
            customer_name=None,
            customer_reference=None,
            po_number=None,
            order_date=None,
            requested_delivery_date=None,
            currency=None,
            lines=(),
            notes=None,
            evidence=(),
        )

    with pytest.raises(ValueError):
        ExtractionDraft(
            source_sha256="a" * 64,
            source_document_type=SourceDocumentType.EMAIL_BODY,
            customer_name=None,
            customer_reference=None,
            po_number=None,
            order_date=None,
            requested_delivery_date=None,
            currency=None,
            lines=[],  # type: ignore[arg-type]
            notes=None,
            evidence=(),
        )


def test_extraction_error_hierarchy_and_public_messages_are_safe() -> None:
    errors = (
        ExtractionResponseError("response field is invalid"),
        ProviderError("provider request failed"),
        ProviderTimeoutError("provider request timed out"),
    )

    assert issubclass(ExtractionResponseError, ExtractionError)
    assert issubclass(ProviderError, ExtractionError)
    assert issubclass(ProviderTimeoutError, ProviderError)
    for error in errors:
        assert "private-document-body" not in str(error)
        assert "AIza-secret" not in str(error)
        assert "raw-provider-response" not in str(error)
