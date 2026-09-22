from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from opsflow.domain.errors import DomainValidationError
from opsflow.review.contracts import (
    OperatorContext,
    OperatorRole,
    ReviewChange,
    ReviewDraft,
    ReviewLine,
    ReviewRevision,
)

ORDER_ID = UUID(int=1)
SNAPSHOT_ID = UUID(int=2)
REVISION_ID = UUID(int=3)


def make_line(**overrides: object) -> ReviewLine:
    values: dict[str, object] = {
        "sku": "SKU-001",
        "description": "Widget",
        "quantity": Decimal("2"),
        "submitted_price": Decimal("10"),
    }
    values.update(overrides)
    return ReviewLine(**values)


def make_draft(**overrides: object) -> ReviewDraft:
    values: dict[str, object] = {
        "customer_name": "Acme Industries",
        "customer_reference": "CUST-001",
        "po_number": "PO-001",
        "order_date": date(2026, 9, 1),
        "requested_delivery_date": date(2026, 9, 15),
        "currency": "USD",
        "lines": (make_line(),),
    }
    values.update(overrides)
    return ReviewDraft(**values)


def make_revision(**overrides: object) -> ReviewRevision:
    values: dict[str, object] = {
        "id": REVISION_ID,
        "order_id": ORDER_ID,
        "extraction_snapshot_id": SNAPSHOT_ID,
        "revision_number": 1,
        "payload": make_draft(),
        "changes": (ReviewChange("po_number", "PO-000", "PO-001"),),
        "actor": "reviewer-demo",
        "created_at": datetime(2026, 9, 20, 12, tzinfo=UTC),
    }
    values.update(overrides)
    return ReviewRevision(**values)


def test_operator_roles_have_exact_members() -> None:
    assert [(role.name, role.value) for role in OperatorRole] == [
        ("REVIEWER", "REVIEWER"),
        ("APPROVER", "APPROVER"),
        ("ELEVATED_APPROVER", "ELEVATED_APPROVER"),
    ]


def test_all_review_records_are_frozen_and_slotted() -> None:
    records = (
        (OperatorContext("reviewer-demo", OperatorRole.REVIEWER), "actor", "new-actor"),
        (make_line(), "sku", "SKU-002"),
        (make_draft(), "currency", "EUR"),
        (ReviewChange("po_number", "PO-000", "PO-001"), "field_path", "currency"),
        (make_revision(), "actor", "new-actor"),
    )

    for record, field, replacement in records:
        assert not hasattr(record, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(record, field, replacement)


@pytest.mark.parametrize("actor", ["", " ", "\t", "x" * 129])
def test_operator_context_rejects_blank_or_overlong_actor(actor: str) -> None:
    with pytest.raises(DomainValidationError):
        OperatorContext(actor, OperatorRole.REVIEWER)


def test_operator_context_requires_operator_role() -> None:
    with pytest.raises(DomainValidationError):
        OperatorContext("reviewer-demo", "REVIEWER")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sku", " "),
        ("description", "\t"),
    ],
)
def test_review_line_rejects_blank_optional_text(field: str, value: str) -> None:
    with pytest.raises(DomainValidationError):
        make_line(**{field: value})


@pytest.mark.parametrize("field", ["sku", "description"])
def test_review_line_rejects_non_string_optional_text(field: str) -> None:
    with pytest.raises(DomainValidationError):
        make_line(**{field: 3})


@pytest.mark.parametrize("field", ["quantity", "submitted_price"])
@pytest.mark.parametrize(
    "value",
    [2, 2.0, True, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_review_line_rejects_non_finite_or_non_decimal_values(field: str, value: object) -> None:
    with pytest.raises(DomainValidationError):
        make_line(**{field: value})


def test_review_draft_accepts_business_invalid_values_for_engine_validation() -> None:
    draft = make_draft(
        currency="not-a-supported-currency",
        lines=(make_line(quantity=Decimal("-2"), submitted_price=Decimal("-1")),),
    )

    assert draft.currency == "not-a-supported-currency"
    assert draft.lines[0].quantity == Decimal("-2")
    assert draft.lines[0].submitted_price == Decimal("-1")


def test_review_line_accepts_missing_business_values() -> None:
    assert make_line(sku=None, description=None, quantity=None, submitted_price=None) == ReviewLine(
        None, None, None, None
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("customer_name", " "),
        ("customer_reference", "\t"),
        ("po_number", ""),
        ("currency", "\n"),
    ],
)
def test_review_draft_rejects_blank_optional_text(field: str, value: str) -> None:
    with pytest.raises(DomainValidationError):
        make_draft(**{field: value})


@pytest.mark.parametrize("field", ["customer_name", "customer_reference", "po_number", "currency"])
def test_review_draft_rejects_non_string_optional_text(field: str) -> None:
    with pytest.raises(DomainValidationError):
        make_draft(**{field: 7})


@pytest.mark.parametrize("field", ["order_date", "requested_delivery_date"])
@pytest.mark.parametrize("value", ["2026-09-01", datetime(2026, 9, 1, tzinfo=UTC)])
def test_review_draft_requires_exact_date_values(field: str, value: object) -> None:
    with pytest.raises(DomainValidationError):
        make_draft(**{field: value})


@pytest.mark.parametrize("lines", [[], [make_line()], ("not a review line",)])
def test_review_draft_requires_immutable_review_line_tuple(lines: object) -> None:
    with pytest.raises(DomainValidationError):
        make_draft(lines=lines)


def test_review_draft_accepts_empty_immutable_lines() -> None:
    assert make_draft(lines=()).lines == ()


@pytest.mark.parametrize("revision_number", [0, -1, True, 1.5])
def test_review_revision_requires_positive_integer_number(revision_number: object) -> None:
    with pytest.raises(DomainValidationError):
        make_revision(revision_number=revision_number)


@pytest.mark.parametrize("field", ["id", "order_id", "extraction_snapshot_id"])
def test_review_revision_requires_uuid_ownership_fields(field: str) -> None:
    with pytest.raises(DomainValidationError):
        make_revision(**{field: "not-a-uuid"})


def test_review_revision_requires_review_draft_and_immutable_changes() -> None:
    with pytest.raises(DomainValidationError):
        make_revision(payload={})
    with pytest.raises(DomainValidationError):
        make_revision(changes=[ReviewChange("po_number", "old", "new")])


@pytest.mark.parametrize("actor", ["", " ", "x" * 129])
def test_review_revision_rejects_blank_or_overlong_actor(actor: str) -> None:
    with pytest.raises(DomainValidationError):
        make_revision(actor=actor)


@pytest.mark.parametrize(
    "created_at",
    [datetime(2026, 9, 20), "2026-09-20T12:00:00Z"],
)
def test_review_revision_requires_timezone_aware_datetime(created_at: object) -> None:
    with pytest.raises(DomainValidationError):
        make_revision(created_at=created_at)


def test_review_revision_preserves_distinct_order_and_snapshot_ownership_ids() -> None:
    revision = make_revision()

    assert revision.order_id == ORDER_ID
    assert revision.extraction_snapshot_id == SNAPSHOT_ID
    assert revision.revision_number == 1
