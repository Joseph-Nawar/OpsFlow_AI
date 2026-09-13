from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from opsflow.domain import (
    AuditEvent,
    DomainValidationError,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)

LINE_ID = UUID(int=1)
DOCUMENT_ID = UUID(int=2)
ORDER_ID = UUID(int=3)
SHA256_LOWER = "a" * 64
SHA256_UPPER = "A" * 64


def make_line(**overrides: object) -> OrderLine:
    values: dict[str, object] = {
        "id": LINE_ID,
        "sku": "SKU-001",
        "description": None,
        "quantity": Decimal("2"),
        "submitted_price": None,
        "trusted_catalogue_price": None,
    }
    values.update(overrides)
    return OrderLine(**values)


def make_document(**overrides: object) -> SourceDocument:
    values: dict[str, object] = {
        "id": DOCUMENT_ID,
        "document_type": SourceDocumentType.PDF,
        "name": "purchase-order.pdf",
        "mime_type": "application/pdf",
        "sha256": SHA256_LOWER,
        "message_id": None,
        "storage_reference": None,
        "metadata": (("source", "email"),),
    }
    values.update(overrides)
    return SourceDocument(**values)


def test_domain_validation_error_is_value_error() -> None:
    assert issubclass(DomainValidationError, ValueError)


def test_source_document_type_has_exact_values() -> None:
    assert [member.name for member in SourceDocumentType] == [
        "EMAIL_BODY",
        "PDF",
        "XLSX",
        "CSV",
        "FORM",
    ]


def test_validation_severity_has_exact_values() -> None:
    assert [member.name for member in ValidationSeverity] == [
        "INFO",
        "WARNING",
        "ERROR",
    ]


def test_order_line_accepts_positive_decimal_quantity() -> None:
    line = make_line(quantity=Decimal("1.25"))

    assert line.quantity == Decimal("1.25")


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
def test_order_line_rejects_non_positive_quantity(quantity: Decimal) -> None:
    with pytest.raises(DomainValidationError):
        make_line(quantity=quantity)


@pytest.mark.parametrize("quantity", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_order_line_rejects_non_finite_quantity(quantity: Decimal) -> None:
    with pytest.raises(DomainValidationError):
        make_line(quantity=quantity)


def test_order_line_rejects_non_decimal_quantity() -> None:
    with pytest.raises(DomainValidationError):
        make_line(quantity=2)


@pytest.mark.parametrize("field", ["submitted_price", "trusted_catalogue_price"])
@pytest.mark.parametrize(
    "price", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_order_line_rejects_negative_or_non_finite_price(field: str, price: Decimal) -> None:
    with pytest.raises(DomainValidationError):
        make_line(**{field: price})


def test_order_line_rejects_non_decimal_price() -> None:
    with pytest.raises(DomainValidationError):
        make_line(submitted_price=1)


def test_order_line_requires_sku_or_meaningful_description() -> None:
    with pytest.raises(DomainValidationError):
        make_line(sku="  ", description="\t")


def test_order_line_accepts_description_only() -> None:
    line = make_line(sku=None, description="Blue widget")

    assert line.sku is None


def test_order_line_accepts_sku_only() -> None:
    line = make_line(sku="SKU-001", description=None)

    assert line.description is None


def test_order_line_is_frozen() -> None:
    line = make_line()

    with pytest.raises(FrozenInstanceError):
        line.quantity = Decimal("3")  # type: ignore[misc]


@pytest.mark.parametrize("sha256", [SHA256_LOWER, SHA256_UPPER])
def test_source_document_accepts_case_insensitive_sha256(sha256: str) -> None:
    document = make_document(sha256=sha256)

    assert document.sha256 == sha256


@pytest.mark.parametrize("sha256", ["a" * 63, "a" * 65, "g" * 64, "é" * 32])
def test_source_document_rejects_invalid_sha256(sha256: str) -> None:
    with pytest.raises(DomainValidationError):
        make_document(sha256=sha256)


@pytest.mark.parametrize("field", ["name", "mime_type"])
def test_source_document_rejects_blank_required_text(field: str) -> None:
    with pytest.raises(DomainValidationError):
        make_document(**{field: "  "})


def test_source_document_accepts_immutable_metadata() -> None:
    document = make_document(metadata=(("source", "email"), ("sender", "buyer@example.test")))

    assert document.metadata == (("source", "email"), ("sender", "buyer@example.test"))


@pytest.mark.parametrize(
    "metadata",
    [
        {"source": "email"},
        [("source", "email")],
        (("source", 1),),
        ((1, "email"),),
        (("source", "email", "extra"),),
    ],
)
def test_source_document_rejects_invalid_metadata(metadata: object) -> None:
    with pytest.raises(DomainValidationError):
        make_document(metadata=metadata)


def test_source_document_is_frozen() -> None:
    document = make_document()

    with pytest.raises(FrozenInstanceError):
        document.name = "changed.pdf"  # type: ignore[misc]


def test_validation_issue_accepts_valid_values() -> None:
    issue = ValidationIssue(
        rule_code="PRICE_MISMATCH",
        severity=ValidationSeverity.WARNING,
        field="lines[0].submitted_price",
        expected=Decimal("10.00"),
        actual=Decimal("12.00"),
        explanation="Submitted price differs from the trusted catalogue price.",
    )

    assert issue.field == "lines[0].submitted_price"


@pytest.mark.parametrize("field", ["rule_code", "explanation"])
def test_validation_issue_rejects_blank_required_text(field: str) -> None:
    values: dict[str, object] = {
        "rule_code": "RULE-1",
        "severity": ValidationSeverity.INFO,
        "field": None,
        "expected": None,
        "actual": None,
        "explanation": "An informational issue.",
    }
    values[field] = "  "

    with pytest.raises(DomainValidationError):
        ValidationIssue(**values)


def test_validation_issue_rejects_supplied_blank_field() -> None:
    with pytest.raises(DomainValidationError):
        ValidationIssue("RULE-1", ValidationSeverity.ERROR, "\t", None, None, "Bad value")


def test_validation_issue_accepts_missing_field() -> None:
    issue = ValidationIssue("RULE-1", ValidationSeverity.INFO, None, None, None, "Informational")

    assert issue.field is None


def test_validation_issue_is_frozen() -> None:
    issue = ValidationIssue("RULE-1", ValidationSeverity.INFO, None, None, None, "Informational")

    with pytest.raises(FrozenInstanceError):
        issue.rule_code = "RULE-2"  # type: ignore[misc]


def test_audit_event_accepts_timezone_aware_timestamp() -> None:
    event = AuditEvent(
        id=UUID(int=4),
        order_id=ORDER_ID,
        event_type="RECEIVED",
        actor="intake",
        occurred_at=datetime(2026, 9, 13, 12, 0, tzinfo=UTC),
        description="Order received from email intake.",
    )

    assert event.occurred_at.tzinfo is not None


def test_audit_event_rejects_naive_timestamp() -> None:
    with pytest.raises(DomainValidationError):
        AuditEvent(
            UUID(int=4), ORDER_ID, "RECEIVED", "intake", datetime(2026, 9, 13, 12), "Received"
        )


@pytest.mark.parametrize("field", ["event_type", "actor", "description"])
def test_audit_event_rejects_blank_required_text(field: str) -> None:
    values: dict[str, object] = {
        "id": UUID(int=4),
        "order_id": ORDER_ID,
        "event_type": "RECEIVED",
        "actor": "intake",
        "occurred_at": datetime(2026, 9, 13, 12, tzinfo=UTC),
        "description": "Received",
    }
    values[field] = "\n"

    with pytest.raises(DomainValidationError):
        AuditEvent(**values)


def test_audit_event_is_frozen() -> None:
    event = AuditEvent(
        UUID(int=4),
        ORDER_ID,
        "RECEIVED",
        "intake",
        datetime(2026, 9, 13, 12, tzinfo=UTC),
        "Received",
    )

    with pytest.raises(FrozenInstanceError):
        event.actor = "changed"  # type: ignore[misc]
