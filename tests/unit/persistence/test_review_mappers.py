"""Strict mappings for immutable human-review persistence records."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from opsflow.domain import DomainValidationError
from opsflow.persistence.mappers import review_revision_from_model, review_revision_to_model
from opsflow.persistence.models import ReviewRevisionModel
from opsflow.review import ReviewChange, ReviewDraft, ReviewLine, ReviewRevision


def _revision() -> ReviewRevision:
    previous_lines = [
        {"sku": "SKU-1", "description": None, "quantity": "2", "submitted_price": None}
    ]
    candidate_lines = [
        {"sku": "SKU-1", "description": None, "quantity": "3", "submitted_price": None}
    ]
    return ReviewRevision(
        id=uuid4(),
        order_id=uuid4(),
        extraction_snapshot_id=uuid4(),
        revision_number=1,
        payload=ReviewDraft(
            customer_name=None,
            customer_reference="CUST-1",
            po_number="PO-1",
            order_date=date(2026, 9, 19),
            requested_delivery_date=None,
            currency="USD",
            lines=(ReviewLine("SKU-1", None, Decimal("3.00"), None),),
        ),
        changes=(
            ReviewChange("customer_reference", None, "CUST-1"),
            ReviewChange("order_date", None, "2026-09-19"),
            ReviewChange("lines", previous_lines, candidate_lines),
        ),
        actor="reviewer-demo",
        created_at=datetime(2026, 9, 19, 12, 30, tzinfo=UTC),
    )


def test_review_revision_mapper_round_trips_canonical_payload_and_ordered_changes() -> None:
    revision = _revision()

    row = review_revision_to_model(revision)
    restored = review_revision_from_model(row)

    assert restored == revision
    assert row.payload == {
        "customer_name": None,
        "customer_reference": "CUST-1",
        "po_number": "PO-1",
        "order_date": "2026-09-19",
        "requested_delivery_date": None,
        "currency": "USD",
        "lines": [{"sku": "SKU-1", "description": None, "quantity": "3", "submitted_price": None}],
    }
    assert row.changes == [
        {"field_path": "customer_reference", "old_value": None, "new_value": "CUST-1"},
        {"field_path": "order_date", "old_value": None, "new_value": "2026-09-19"},
        {
            "field_path": "lines",
            "old_value": [
                {"sku": "SKU-1", "description": None, "quantity": "2", "submitted_price": None}
            ],
            "new_value": [
                {"sku": "SKU-1", "description": None, "quantity": "3", "submitted_price": None}
            ],
        },
    ]


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("payload", {"customer_reference": "CUST-1"}),
        ("payload", {"customer_name": None}),
        ("changes", [{"field_path": "unknown", "old_value": None, "new_value": "x"}]),
        (
            "changes",
            [{"field_path": "customer_reference", "old_value": "same", "new_value": "same"}],
        ),
    ],
)
def test_review_revision_mapper_rejects_noncanonical_json(
    field_name: str, invalid_value: object
) -> None:
    row = review_revision_to_model(_revision())
    setattr(row, field_name, invalid_value)

    with pytest.raises(DomainValidationError):
        review_revision_from_model(row)


def test_review_revision_mapper_rejects_naive_created_at() -> None:
    row = review_revision_to_model(_revision())
    row.created_at = datetime(2026, 9, 19, 12, 30)

    with pytest.raises(DomainValidationError):
        review_revision_from_model(row)


def test_review_revision_mapper_rejects_wrong_row_and_invalid_structure() -> None:
    with pytest.raises(DomainValidationError, match="ReviewRevisionModel"):
        review_revision_from_model(object())  # type: ignore[arg-type]

    invalid = _revision()
    with pytest.raises(DomainValidationError, match="positive integer"):
        ReviewRevision(
            id=invalid.id,
            order_id=invalid.order_id,
            extraction_snapshot_id=invalid.extraction_snapshot_id,
            revision_number=0,
            payload=invalid.payload,
            changes=invalid.changes,
            actor=invalid.actor,
            created_at=invalid.created_at,
        )


def test_revision_model_has_no_mutation_helpers() -> None:
    assert not hasattr(ReviewRevisionModel, "update")
    assert not hasattr(ReviewRevisionModel, "delete")
