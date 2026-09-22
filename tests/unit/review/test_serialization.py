from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from opsflow.domain.errors import DomainValidationError
from opsflow.domain.records import SourceDocumentType
from opsflow.extraction.models import Evidence, ExtractedLine, ExtractionDraft
from opsflow.review.contracts import ReviewChange, ReviewDraft, ReviewLine, ReviewRevision
from opsflow.review.serialization import (
    compose_extraction_draft,
    compute_review_changes,
    project_effective_review_draft,
    review_changes_from_payload,
    review_changes_to_payload,
    review_draft_from_extraction,
    review_draft_from_payload,
    review_draft_to_payload,
)

SOURCE_SHA = "a" * 64


def make_review_line(
    sku: str | None = "SKU-001",
    description: str | None = "Widget",
    quantity: Decimal | None = Decimal("2"),
    submitted_price: Decimal | None = Decimal("10"),
) -> ReviewLine:
    return ReviewLine(sku, description, quantity, submitted_price)


def make_review_draft(**overrides: object) -> ReviewDraft:
    values: dict[str, object] = {
        "customer_name": "Acme Industries",
        "customer_reference": "CUST-001",
        "po_number": "PO-001",
        "order_date": date(2026, 9, 1),
        "requested_delivery_date": date(2026, 9, 15),
        "currency": "USD",
        "lines": (make_review_line(),),
    }
    values.update(overrides)
    return ReviewDraft(**values)


def make_extraction_draft() -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256=SOURCE_SHA,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Original customer",
        customer_reference="ORIGINAL-CUSTOMER",
        po_number="ORIGINAL-PO",
        order_date=date(2026, 8, 1),
        requested_delivery_date=date(2026, 8, 15),
        currency="EUR",
        lines=(ExtractedLine("ORIGINAL-SKU", "Original line", Decimal("1"), Decimal("3")),),
        notes="Original extraction note",
        evidence=(Evidence("po_number", "page:1", "ORIGINAL-PO"),),
    )


def make_revision(revision_number: int, payload: ReviewDraft) -> ReviewRevision:
    return ReviewRevision(
        id=UUID(int=revision_number),
        order_id=UUID(int=100),
        extraction_snapshot_id=UUID(int=200),
        revision_number=revision_number,
        payload=payload,
        changes=(ReviewChange("po_number", "PO-OLD", payload.po_number),),
        actor="reviewer-demo",
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )


def valid_payload() -> dict[str, object]:
    return {
        "customer_name": "Acme Industries",
        "customer_reference": None,
        "po_number": "PO-001",
        "order_date": "2026-09-01",
        "requested_delivery_date": "2026-09-15",
        "currency": "USD",
        "lines": [
            {
                "sku": "SKU-001",
                "description": "Widget",
                "quantity": "2.5",
                "submitted_price": "10",
            }
        ],
    }


def test_review_draft_serialization_has_exact_ordered_shape_and_canonical_scalars() -> None:
    draft = make_review_draft(
        customer_name="  Acme  Industries ",
        customer_reference=None,
        order_date=date(2026, 9, 20),
        requested_delivery_date=None,
        currency="usd",
        lines=(
            make_review_line(quantity=Decimal("2.500"), submitted_price=Decimal("1E+3")),
            make_review_line(None, None, Decimal("-0.000"), None),
        ),
    )

    payload = review_draft_to_payload(draft)

    assert list(payload) == [
        "customer_name",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "lines",
    ]
    assert payload == {
        "customer_name": "  Acme  Industries ",
        "customer_reference": None,
        "po_number": "PO-001",
        "order_date": "2026-09-20",
        "requested_delivery_date": None,
        "currency": "usd",
        "lines": [
            {
                "sku": "SKU-001",
                "description": "Widget",
                "quantity": "2.5",
                "submitted_price": "1000",
            },
            {
                "sku": None,
                "description": None,
                "quantity": "0",
                "submitted_price": None,
            },
        ],
    }
    assert list(payload["lines"][0]) == [
        "sku",
        "description",
        "quantity",
        "submitted_price",
    ]


def test_review_draft_deserialization_round_trips_to_immutable_values() -> None:
    restored = review_draft_from_payload(valid_payload())

    assert restored == make_review_draft(
        customer_reference=None,
        lines=(make_review_line(quantity=Decimal("2.5")),),
    )
    assert type(restored.lines) is tuple


@pytest.mark.parametrize("mutation", ["missing", "extra", "source", "notes", "evidence", "actor"])
def test_review_draft_deserialization_rejects_non_exact_root_shape(mutation: str) -> None:
    payload = valid_payload()
    if mutation == "missing":
        del payload["customer_reference"]
    elif mutation == "extra":
        payload["unexpected"] = "value"
    else:
        payload[mutation] = "not editable"

    with pytest.raises(DomainValidationError):
        review_draft_from_payload(payload)


@pytest.mark.parametrize("mutation", ["missing", "extra", "evidence", "provider"])
def test_review_draft_deserialization_rejects_non_exact_line_shape(mutation: str) -> None:
    payload = valid_payload()
    line = payload["lines"][0]
    if mutation == "missing":
        del line["sku"]
    elif mutation == "extra":
        line["unexpected"] = "value"
    else:
        line[mutation] = "not editable"

    with pytest.raises(DomainValidationError):
        review_draft_from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("order_date", "2026-9-01"),
        ("order_date", "2026-02-30"),
        ("requested_delivery_date", "2026-09-15T00:00:00"),
        ("order_date", date(2026, 9, 1)),
    ],
)
def test_review_draft_deserialization_rejects_noncanonical_dates(field: str, value: object) -> None:
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(DomainValidationError):
        review_draft_from_payload(payload)


@pytest.mark.parametrize(
    "value",
    ["2.50", "2E+0", "-0", "01", "+2", 2, 2.0, Decimal("2"), "NaN", "Infinity"],
)
def test_review_draft_deserialization_rejects_noncanonical_or_non_decimal_values(
    value: object,
) -> None:
    payload = valid_payload()
    payload["lines"][0]["quantity"] = value

    with pytest.raises(DomainValidationError):
        review_draft_from_payload(payload)


@pytest.mark.parametrize("payload", [[], (), None, "{}"])
def test_review_draft_deserialization_requires_ordinary_json_object(payload: object) -> None:
    with pytest.raises(DomainValidationError):
        review_draft_from_payload(payload)


def test_review_draft_deserialization_requires_json_array_for_lines() -> None:
    payload = valid_payload()
    payload["lines"] = tuple(payload["lines"])

    with pytest.raises(DomainValidationError):
        review_draft_from_payload(payload)


def test_review_draft_projection_uses_original_when_no_revision_exists() -> None:
    original = make_review_draft()

    assert project_effective_review_draft(original, None) is original


def test_review_draft_projection_uses_the_highest_revision_payload() -> None:
    original = make_review_draft()
    earlier = make_revision(1, make_review_draft(po_number="PO-REV-1"))
    latest_payload = make_review_draft(po_number="PO-REV-2")
    latest = make_revision(2, latest_payload)

    assert project_effective_review_draft(original, latest) is latest_payload
    assert project_effective_review_draft(original, earlier) is earlier.payload


def test_review_draft_from_extraction_projects_only_editable_business_values() -> None:
    extraction = make_extraction_draft()

    review_draft = review_draft_from_extraction(extraction)

    assert review_draft == ReviewDraft(
        customer_name="Original customer",
        customer_reference="ORIGINAL-CUSTOMER",
        po_number="ORIGINAL-PO",
        order_date=date(2026, 8, 1),
        requested_delivery_date=date(2026, 8, 15),
        currency="EUR",
        lines=(ReviewLine("ORIGINAL-SKU", "Original line", Decimal("1"), Decimal("3")),),
    )


def test_candidate_composition_preserves_original_provenance_and_uses_candidate_values() -> None:
    original = make_extraction_draft()
    candidate = make_review_draft(
        customer_name="Corrected customer",
        customer_reference="CUST-001",
        po_number="PO-CORRECTED",
        lines=(make_review_line("SKU-002", "Gadget", Decimal("4"), Decimal("12")),),
    )

    composed = compose_extraction_draft(original, candidate)

    assert composed.source_sha256 == original.source_sha256
    assert composed.source_document_type is original.source_document_type
    assert composed.notes is original.notes
    assert composed.evidence is original.evidence
    assert composed.customer_name == "Corrected customer"
    assert composed.customer_reference == "CUST-001"
    assert composed.po_number == "PO-CORRECTED"
    assert composed.lines == (ExtractedLine("SKU-002", "Gadget", Decimal("4"), Decimal("12")),)


def test_compute_review_changes_orders_scalar_changes_and_serializes_canonically() -> None:
    previous = make_review_draft()
    candidate = make_review_draft(
        customer_name="New customer",
        customer_reference="CUST-002",
        po_number="PO-002",
        order_date=date(2026, 9, 2),
        requested_delivery_date=date(2026, 9, 16),
        currency="EUR",
    )

    changes = compute_review_changes(previous, candidate)

    assert [change.field_path for change in changes] == [
        "customer_name",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
    ]
    assert review_changes_to_payload(changes) == [
        {
            "field_path": "customer_name",
            "old_value": "Acme Industries",
            "new_value": "New customer",
        },
        {
            "field_path": "customer_reference",
            "old_value": "CUST-001",
            "new_value": "CUST-002",
        },
        {"field_path": "po_number", "old_value": "PO-001", "new_value": "PO-002"},
        {"field_path": "order_date", "old_value": "2026-09-01", "new_value": "2026-09-02"},
        {
            "field_path": "requested_delivery_date",
            "old_value": "2026-09-15",
            "new_value": "2026-09-16",
        },
        {"field_path": "currency", "old_value": "USD", "new_value": "EUR"},
    ]
    assert review_changes_from_payload(review_changes_to_payload(changes)) == changes


@pytest.mark.parametrize(
    ("old_lines", "new_lines", "expected_old", "expected_new"),
    [
        (
            (make_review_line(),),
            (make_review_line(quantity=Decimal("3")),),
            [{"sku": "SKU-001", "description": "Widget", "quantity": "2", "submitted_price": "10"}],
            [{"sku": "SKU-001", "description": "Widget", "quantity": "3", "submitted_price": "10"}],
        ),
        (
            (make_review_line(),),
            (
                make_review_line(),
                make_review_line("SKU-002", "Gadget", Decimal("1"), Decimal("25")),
            ),
            [
                {
                    "sku": "SKU-001",
                    "description": "Widget",
                    "quantity": "2",
                    "submitted_price": "10",
                }
            ],
            [
                {
                    "sku": "SKU-001",
                    "description": "Widget",
                    "quantity": "2",
                    "submitted_price": "10",
                },
                {
                    "sku": "SKU-002",
                    "description": "Gadget",
                    "quantity": "1",
                    "submitted_price": "25",
                },
            ],
        ),
        (
            (
                make_review_line(),
                make_review_line("SKU-002", "Gadget", Decimal("1"), Decimal("25")),
            ),
            (make_review_line(),),
            [
                {
                    "sku": "SKU-001",
                    "description": "Widget",
                    "quantity": "2",
                    "submitted_price": "10",
                },
                {
                    "sku": "SKU-002",
                    "description": "Gadget",
                    "quantity": "1",
                    "submitted_price": "25",
                },
            ],
            [
                {
                    "sku": "SKU-001",
                    "description": "Widget",
                    "quantity": "2",
                    "submitted_price": "10",
                }
            ],
        ),
        (
            (
                make_review_line(),
                make_review_line("SKU-002", "Gadget", Decimal("1"), Decimal("25")),
            ),
            (
                make_review_line("SKU-002", "Gadget", Decimal("1"), Decimal("25")),
                make_review_line(),
            ),
            [
                {
                    "sku": "SKU-001",
                    "description": "Widget",
                    "quantity": "2",
                    "submitted_price": "10",
                },
                {
                    "sku": "SKU-002",
                    "description": "Gadget",
                    "quantity": "1",
                    "submitted_price": "25",
                },
            ],
            [
                {
                    "sku": "SKU-002",
                    "description": "Gadget",
                    "quantity": "1",
                    "submitted_price": "25",
                },
                {
                    "sku": "SKU-001",
                    "description": "Widget",
                    "quantity": "2",
                    "submitted_price": "10",
                },
            ],
        ),
    ],
)
def test_any_ordered_line_difference_is_one_complete_aggregate_change(
    old_lines: tuple[ReviewLine, ...],
    new_lines: tuple[ReviewLine, ...],
    expected_old: list[dict[str, str | None]],
    expected_new: list[dict[str, str | None]],
) -> None:
    changes = compute_review_changes(
        make_review_draft(lines=old_lines),
        make_review_draft(lines=new_lines),
    )

    assert len(changes) == 1
    assert changes[0].field_path == "lines"
    assert changes[0].old_value == expected_old
    assert changes[0].new_value == expected_new


def test_equal_canonical_review_drafts_produce_no_changes() -> None:
    previous = make_review_draft(lines=(make_review_line(quantity=Decimal("2.000")),))
    candidate = make_review_draft(lines=(make_review_line(quantity=Decimal("2")),))

    assert compute_review_changes(previous, candidate) == ()


def test_review_change_deserializer_rejects_wrong_shapes_and_unknown_paths() -> None:
    for payload in (
        {},
        [{"field_path": "po_number", "old_value": "PO-1"}],
        [{"field_path": "lines[0].sku", "old_value": "SKU-1", "new_value": "SKU-2"}],
        [{"field_path": "order_date", "old_value": "2026-9-1", "new_value": "2026-09-02"}],
    ):
        with pytest.raises(DomainValidationError):
            review_changes_from_payload(payload)
