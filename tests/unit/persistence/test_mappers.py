"""Unit tests for explicit Phase 1 domain and persistence mapping."""

from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from opsflow.domain import (
    AuditEvent,
    DomainValidationError,
    Order,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.extraction.models import Evidence, ExtractedLine, ExtractionDraft
from opsflow.persistence.mappers import (
    PersistedExtractionSnapshot,
    audit_event_from_model,
    extraction_draft_from_payload,
    extraction_draft_to_payload,
    extraction_snapshot_from_model,
    extraction_snapshot_to_model,
    line_to_model,
    order_from_models,
    order_to_model,
    source_document_from_model,
    source_document_to_model,
    validation_issue_from_model,
)
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    SourceDocumentModel,
    ValidationIssueModel,
)

ORDER_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 9, 14, 10, 30, tzinfo=UTC)
SNAPSHOT_ID = UUID("55555555-5555-4555-8555-555555555555")
SOURCE_DOCUMENT_ID = UUID("66666666-6666-4666-8666-666666666666")


def _draft() -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.PDF,
        customer_name="  Acme  Industries ",
        customer_reference=" CUST-1 ",
        po_number="PO-1",
        order_date=date(2026, 9, 14),
        requested_delivery_date=date(2026, 10, 1),
        currency="USD",
        lines=(
            ExtractedLine(
                sku="SKU-1",
                description="A widget  ",
                quantity=Decimal("2.500"),
                submitted_price=Decimal("1E+3"),
            ),
            ExtractedLine(
                sku=None,
                description=None,
                quantity=None,
                submitted_price=None,
            ),
        ),
        notes=None,
        evidence=(
            Evidence(field_path="po_number", source_location="page:1", quote="PO-1"),
            Evidence(field_path="lines[0].sku", source_location="table:1", quote="SKU-1"),
        ),
    )


def _snapshot(draft: ExtractionDraft | None = None) -> PersistedExtractionSnapshot:
    return PersistedExtractionSnapshot(
        id=SNAPSHOT_ID,
        order_id=ORDER_ID,
        source_document_id=SOURCE_DOCUMENT_ID,
        source_sha256=(draft or _draft()).source_sha256,
        source_document_type=(draft or _draft()).source_document_type,
        draft=draft or _draft(),
        created_at=CREATED_AT,
    )


def test_minimal_order_mapping_round_trips_through_phase1_constructor() -> None:
    order = Order.received(id=ORDER_ID)

    row = order_to_model(order, CREATED_AT)
    restored = order_from_models(row, [], [])

    assert restored == order
    assert row.created_at == CREATED_AT
    assert row.state == "RECEIVED"
    assert row.failure_origin is None


def test_populated_order_mapping_preserves_types_values_and_positions() -> None:
    line = OrderLine(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        sku="SKU-1",
        description="A widget",
        quantity=Decimal("5.00"),
        submitted_price=Decimal("10.50"),
        trusted_catalogue_price=Decimal("11.00"),
    )
    document = SourceDocument(
        id=UUID("33333333-3333-4333-8333-333333333333"),
        document_type=SourceDocumentType.EMAIL_BODY,
        name="order email",
        mime_type="message/rfc822",
        sha256="a" * 64,
        message_id="message-1",
        storage_reference="mailbox/message-1",
        metadata=(
            ("message_source", "email"),
            ("message_source", "archive"),
            ("mailbox", "orders"),
        ),
    )
    order = Order.received(
        id=ORDER_ID,
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2026, 9, 14),
        requested_delivery_date=date(2026, 10, 1),
        currency="USD",
        lines=(line,),
        source_documents=(document,),
    )

    line_row = line_to_model(order.id, 0, line)
    document_row = source_document_to_model(order.id, 0, document)
    restored = order_from_models(
        order_to_model(order, CREATED_AT),
        [line_row],
        [document_row],
    )

    assert restored == order
    assert restored.lines[0].quantity == Decimal("5.00")
    assert isinstance(restored.lines[0].quantity, Decimal)
    assert restored.lines[0].submitted_price == Decimal("10.50")
    assert restored.source_documents[0].metadata == document.metadata
    assert document_row.metadata_ == [
        ["message_source", "email"],
        ["message_source", "archive"],
        ["mailbox", "orders"],
    ]


def test_child_mapping_preserves_explicit_positions_and_ordered_metadata() -> None:
    first = OrderLine(
        id=uuid4(),
        sku="FIRST",
        description=None,
        quantity=Decimal("1"),
        submitted_price=None,
        trusted_catalogue_price=None,
    )
    second = OrderLine(
        id=uuid4(),
        sku="SECOND",
        description=None,
        quantity=Decimal("2"),
        submitted_price=None,
        trusted_catalogue_price=None,
    )
    order = Order.received(id=ORDER_ID, lines=(first, second))

    restored = order_from_models(
        order_to_model(order, CREATED_AT),
        [line_to_model(ORDER_ID, 1, second), line_to_model(ORDER_ID, 0, first)],
        [],
    )

    assert restored.lines == (first, second)
    assert [line.id for line in restored.lines] == [first.id, second.id]


def test_validation_issue_and_audit_event_map_as_separate_phase1_records() -> None:
    issue_row = ValidationIssueModel(
        order_id=ORDER_ID,
        position=0,
        rule_code="REQUIRED_PO",
        severity="WARNING",
        field="po_number",
        expected="present",
        actual=None,
        explanation="The purchase-order number is missing.",
    )
    audit = AuditEvent(
        id=UUID("44444444-4444-4444-8444-444444444444"),
        order_id=ORDER_ID,
        event_type="ORDER_RECEIVED",
        actor="system",
        occurred_at=CREATED_AT,
        description="Order received through API intake.",
    )
    audit_row = AuditEventModel(
        id=audit.id,
        order_id=audit.order_id,
        event_type=audit.event_type,
        actor=audit.actor,
        occurred_at=audit.occurred_at,
        description=audit.description,
    )

    issue = validation_issue_from_model(issue_row)
    restored_audit = audit_event_from_model(audit_row)

    assert issue == ValidationIssue(
        rule_code="REQUIRED_PO",
        severity=ValidationSeverity.WARNING,
        field="po_number",
        expected="present",
        actual=None,
        explanation="The purchase-order number is missing.",
    )
    assert restored_audit == audit
    assert restored_audit.occurred_at.tzinfo is not None
    assert restored_audit.occurred_at.utcoffset() is not None


def test_malformed_persisted_state_and_metadata_are_rejected() -> None:
    order_row = order_to_model(Order.received(id=ORDER_ID), CREATED_AT)
    order_row.state = "NOT_A_STATE"
    with pytest.raises(DomainValidationError):
        order_from_models(order_row, [], [])

    failed_order_row = order_to_model(Order.received(id=ORDER_ID), CREATED_AT)
    failed_order_row.state = "FAILED_FINAL"
    with pytest.raises(DomainValidationError):
        order_from_models(failed_order_row, [], [])

    document_row = SourceDocumentModel(
        id=uuid4(),
        order_id=ORDER_ID,
        position=0,
        document_type="FORM",
        name="form",
        mime_type="application/json",
        sha256="b" * 64,
        metadata=[["only-one-value"]],
    )
    with pytest.raises(DomainValidationError):
        source_document_from_model(document_row)


def test_float_numeric_storage_is_rejected_instead_of_converted() -> None:
    order = Order.received(id=ORDER_ID)
    line_row = line_to_model(
        ORDER_ID,
        0,
        OrderLine(
            id=uuid4(),
            sku="SKU",
            description=None,
            quantity=Decimal("1.25"),
            submitted_price=None,
            trusted_catalogue_price=None,
        ),
    )
    line_row.quantity = 1.25  # type: ignore[assignment]

    with pytest.raises(DomainValidationError):
        order_from_models(order_to_model(order, CREATED_AT), [line_row], [])


def test_extraction_draft_payload_has_exact_canonical_shape_and_nulls() -> None:
    assert extraction_draft_to_payload(_draft()) == {
        "source": {"sha256": "a" * 64, "document_type": "PDF"},
        "customer_name": "  Acme  Industries ",
        "customer_reference": " CUST-1 ",
        "po_number": "PO-1",
        "order_date": "2026-09-14",
        "requested_delivery_date": "2026-10-01",
        "currency": "USD",
        "lines": [
            {
                "sku": "SKU-1",
                "description": "A widget  ",
                "quantity": "2.5",
                "submitted_price": "1000",
            },
            {"sku": None, "description": None, "quantity": None, "submitted_price": None},
        ],
        "notes": None,
        "evidence": [
            {"field_path": "po_number", "source_location": "page:1", "quote": "PO-1"},
            {
                "field_path": "lines[0].sku",
                "source_location": "table:1",
                "quote": "SKU-1",
            },
        ],
    }


def test_extraction_draft_payload_round_trip_preserves_values_and_order() -> None:
    draft = _draft()

    restored = extraction_draft_from_payload(extraction_draft_to_payload(draft))

    assert restored == draft
    assert [line.sku for line in restored.lines] == ["SKU-1", None]
    assert [item.field_path for item in restored.evidence] == ["po_number", "lines[0].sku"]
    assert restored.lines[1].quantity is None
    assert restored.lines[1].submitted_price is None


def test_extraction_payload_object_key_order_is_not_semantic() -> None:
    payload = extraction_draft_to_payload(_draft())
    reordered = dict(reversed(tuple(payload.items())))
    reordered["source"] = dict(reversed(tuple(payload["source"].items())))

    assert extraction_draft_from_payload(reordered) == _draft()


@pytest.mark.parametrize(
    ("level", "key"),
    (
        ("top", "notes"),
        ("source", "sha256"),
        ("line", "sku"),
        ("evidence", "quote"),
    ),
)
def test_extraction_payload_rejects_missing_keys_at_every_object_level(
    level: str, key: str
) -> None:
    payload = extraction_draft_to_payload(_draft())
    target: dict[str, object]
    if level == "top":
        target = payload
    elif level == "source":
        target = payload["source"]  # type: ignore[assignment]
    elif level == "line":
        target = payload["lines"][0]  # type: ignore[index]
    else:
        target = payload["evidence"][0]  # type: ignore[index]
    del target[key]

    with pytest.raises(DomainValidationError):
        extraction_draft_from_payload(payload)


@pytest.mark.parametrize(
    ("level", "key"),
    (
        ("top", "provider_response"),
        ("source", "prompt"),
        ("line", "raw_response"),
        ("evidence", "model"),
    ),
)
def test_extraction_payload_rejects_extra_keys_at_every_object_level(level: str, key: str) -> None:
    payload = extraction_draft_to_payload(_draft())
    target: dict[str, object]
    if level == "top":
        target = payload
    elif level == "source":
        target = payload["source"]  # type: ignore[assignment]
    elif level == "line":
        target = payload["lines"][0]  # type: ignore[index]
    else:
        target = payload["evidence"][0]  # type: ignore[index]
    target[key] = "unexpected"

    with pytest.raises(DomainValidationError):
        extraction_draft_from_payload(payload)


@pytest.mark.parametrize(
    "payload_factory",
    (
        lambda payload: [],
        lambda payload: {**payload, "lines": {}},
        lambda payload: {**payload, "evidence": {}},
        lambda payload: {**payload, "customer_name": 3},
        lambda payload: {**payload, "order_date": date(2026, 9, 14)},
        lambda payload: {**payload, "lines": ["not an object"]},
        lambda payload: {**payload, "evidence": ["not an object"]},
    ),
)
def test_extraction_payload_rejects_wrong_types(payload_factory: object) -> None:
    payload = payload_factory(extraction_draft_to_payload(_draft()))  # type: ignore[operator]

    with pytest.raises(DomainValidationError):
        extraction_draft_from_payload(payload)


@pytest.mark.parametrize("value", ("2.50", "2E+0", "-0", "1.0"))
def test_extraction_payload_rejects_noncanonical_decimal_strings(value: str) -> None:
    payload = extraction_draft_to_payload(_draft())
    payload["lines"][0]["quantity"] = value

    with pytest.raises(DomainValidationError):
        extraction_draft_from_payload(payload)


@pytest.mark.parametrize("value", ("2026-9-14", "2026-09-14T00:00:00", "2026-02-30"))
def test_extraction_payload_rejects_noncanonical_dates(value: str) -> None:
    payload = extraction_draft_to_payload(_draft())
    payload["order_date"] = value

    with pytest.raises(DomainValidationError):
        extraction_draft_from_payload(payload)


def test_extraction_snapshot_mapper_round_trips_relational_envelope() -> None:
    snapshot = _snapshot()

    row = extraction_snapshot_to_model(snapshot)
    restored = extraction_snapshot_from_model(row)

    assert row.id == SNAPSHOT_ID
    assert row.order_id == ORDER_ID
    assert row.source_document_id == SOURCE_DOCUMENT_ID
    assert row.source_sha256 == "a" * 64
    assert row.source_document_type == "PDF"
    assert row.created_at == CREATED_AT
    assert restored == snapshot
    assert isinstance(row.payload, dict)


def test_extraction_snapshot_mapper_requires_source_and_relational_envelope_agreement() -> None:
    draft = _draft()
    with pytest.raises(DomainValidationError):
        extraction_snapshot_to_model(
            PersistedExtractionSnapshot(
                id=SNAPSHOT_ID,
                order_id=ORDER_ID,
                source_document_id=SOURCE_DOCUMENT_ID,
                source_sha256="b" * 64,
                source_document_type=SourceDocumentType.PDF,
                draft=draft,
                created_at=CREATED_AT,
            )
        )

    row = ExtractionSnapshotModel(
        id=SNAPSHOT_ID,
        order_id=ORDER_ID,
        source_document_id=SOURCE_DOCUMENT_ID,
        source_sha256="b" * 64,
        source_document_type="PDF",
        payload=extraction_draft_to_payload(draft),
        created_at=CREATED_AT,
    )
    with pytest.raises(DomainValidationError):
        extraction_snapshot_from_model(row)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda row: setattr(row, "source_document_type", "DOC"),
        lambda row: setattr(row, "source_sha256", "A" * 64),
        lambda row: setattr(row, "payload", []),
        lambda row: setattr(row, "created_at", datetime(2026, 9, 14)),
    ),
)
def test_extraction_snapshot_mapper_rejects_invalid_relational_values(mutate: object) -> None:
    row = extraction_snapshot_to_model(_snapshot())
    mutate(row)  # type: ignore[operator]

    with pytest.raises(DomainValidationError):
        extraction_snapshot_from_model(row)


def test_extraction_snapshot_payload_builder_does_not_accept_mutable_draft_collections() -> None:
    draft = _draft()
    invalid = deepcopy(draft)
    object.__setattr__(invalid, "lines", list(draft.lines))

    with pytest.raises(DomainValidationError):
        extraction_draft_to_payload(invalid)
