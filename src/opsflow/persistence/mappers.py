"""Explicit conversion between Phase 1 records and persistence models."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from opsflow.domain import (
    AuditEvent,
    DomainValidationError,
    Order,
    OrderLine,
    OrderState,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.extraction.models import Evidence, ExtractedLine, ExtractionDraft
from opsflow.review import ReviewRevision
from opsflow.review.serialization import (
    review_changes_from_payload,
    review_changes_to_payload,
    review_draft_from_payload,
    review_draft_to_payload,
)

from .models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderLineModel,
    OrderModel,
    ReviewRevisionModel,
    SourceDocumentModel,
    ValidationIssueModel,
)

_DRAFT_KEYS = frozenset(
    {
        "source",
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
)
_SOURCE_KEYS = frozenset({"sha256", "document_type"})
_LINE_KEYS = frozenset({"sku", "description", "quantity", "submitted_price"})
_EVIDENCE_KEYS = frozenset({"field_path", "source_location", "quote"})
_CANONICAL_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", flags=re.ASCII)
_CANONICAL_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_CANONICAL_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class PersistedExtractionSnapshot:
    """Typed persistence envelope for one immutable extraction draft."""

    id: UUID
    order_id: UUID
    source_document_id: UUID
    source_sha256: str
    source_document_type: SourceDocumentType
    draft: ExtractionDraft
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("snapshot id must be a UUID")
        if not isinstance(self.order_id, UUID):
            raise DomainValidationError("snapshot order_id must be a UUID")
        if not isinstance(self.source_document_id, UUID):
            raise DomainValidationError("snapshot source_document_id must be a UUID")
        _require_canonical_sha(self.source_sha256, "snapshot source_sha256")
        if not isinstance(self.source_document_type, SourceDocumentType):
            raise DomainValidationError("snapshot source_document_type is invalid")
        if not isinstance(self.draft, ExtractionDraft):
            raise DomainValidationError("snapshot draft must be an ExtractionDraft")
        if self.source_sha256 != self.draft.source_sha256:
            raise DomainValidationError("snapshot source_sha256 disagrees with draft")
        if self.source_document_type is not self.draft.source_document_type:
            raise DomainValidationError("snapshot document type disagrees with draft")
        _require_aware_datetime(self.created_at, "snapshot created_at")


def order_to_model(order: Order, created_at: datetime) -> OrderModel:
    """Map an Order snapshot and persistence timestamp to an ORM row."""

    _require_aware_datetime(created_at, "created_at")
    return OrderModel(
        id=order.id,
        customer_reference=order.customer_reference,
        po_number=order.po_number,
        order_date=order.order_date,
        requested_delivery_date=order.requested_delivery_date,
        currency=order.currency,
        state=order.state.value,
        failure_origin=order.failure_origin.value if order.failure_origin else None,
        created_at=created_at,
    )


def line_to_model(order_id: UUID, position: int, line: OrderLine) -> OrderLineModel:
    """Map one ordered OrderLine to an ORM row."""

    _require_position(position)
    return OrderLineModel(
        id=line.id,
        order_id=order_id,
        position=position,
        sku=line.sku,
        description=line.description,
        quantity=line.quantity,
        submitted_price=line.submitted_price,
        trusted_catalogue_price=line.trusted_catalogue_price,
    )


def source_document_to_model(
    order_id: UUID, position: int, document: SourceDocument
) -> SourceDocumentModel:
    """Map one ordered SourceDocument to an ORM row."""

    _require_position(position)
    return SourceDocumentModel(
        id=document.id,
        order_id=order_id,
        position=position,
        document_type=document.document_type.value,
        name=document.name,
        mime_type=document.mime_type,
        sha256=document.sha256,
        message_id=document.message_id,
        storage_reference=document.storage_reference,
        metadata_=[list(pair) for pair in document.metadata],
    )


def order_from_models(
    order_row: OrderModel,
    line_rows: Sequence[OrderLineModel],
    document_rows: Sequence[SourceDocumentModel],
) -> Order:
    """Reconstruct a validated Order from explicitly ordered ORM rows."""

    state = _order_state(order_row.state, "state")
    failure_origin = (
        _order_state(order_row.failure_origin, "failure_origin")
        if order_row.failure_origin is not None
        else None
    )
    lines = tuple(
        _line_from_model(row, order_row.id)
        for row in _ordered_rows(line_rows, order_row.id, "order line")
    )
    documents = tuple(
        source_document_from_model(row, expected_order_id=order_row.id)
        for row in _ordered_rows(document_rows, order_row.id, "source document")
    )
    try:
        return Order(
            id=order_row.id,
            customer_reference=order_row.customer_reference,
            po_number=order_row.po_number,
            order_date=order_row.order_date,
            requested_delivery_date=order_row.requested_delivery_date,
            currency=order_row.currency,
            lines=lines,
            source_documents=documents,
            state=state,
            failure_origin=failure_origin,
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted order violates the Phase 1 contract") from error


def validation_issue_from_model(row: ValidationIssueModel) -> ValidationIssue:
    """Map a persisted validation issue to its separate Phase 1 record."""

    _require_position(row.position)
    _require_json_value(row.expected, "expected")
    _require_json_value(row.actual, "actual")
    try:
        severity = ValidationSeverity(row.severity)
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted validation severity is invalid") from error
    try:
        return ValidationIssue(
            rule_code=row.rule_code,
            severity=severity,
            field=row.field,
            expected=row.expected,
            actual=row.actual,
            explanation=row.explanation,
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted validation issue violates Phase 1") from error


def audit_event_to_model(event: AuditEvent) -> AuditEventModel:
    """Map one validated audit event to an ORM row."""

    return AuditEventModel(
        id=event.id,
        order_id=event.order_id,
        event_type=event.event_type,
        actor=event.actor,
        occurred_at=event.occurred_at,
        description=event.description,
    )


def audit_event_from_model(row: AuditEventModel) -> AuditEvent:
    """Map a persisted audit row to its separate Phase 1 record."""

    try:
        return AuditEvent(
            id=row.id,
            order_id=row.order_id,
            event_type=row.event_type,
            actor=row.actor,
            occurred_at=row.occurred_at,
            description=row.description,
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted audit event violates Phase 1") from error


def source_document_from_model(
    row: SourceDocumentModel, *, expected_order_id: UUID | None = None
) -> SourceDocument:
    """Map a persisted source-document row and validate ordered metadata."""

    if expected_order_id is not None and row.order_id != expected_order_id:
        raise DomainValidationError("source document belongs to a different order")
    metadata = _metadata_from_storage(row.metadata_)
    try:
        document_type = SourceDocumentType(row.document_type)
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted source document type is invalid") from error
    try:
        return SourceDocument(
            id=row.id,
            document_type=document_type,
            name=row.name,
            mime_type=row.mime_type,
            sha256=row.sha256,
            message_id=row.message_id,
            storage_reference=row.storage_reference,
            metadata=metadata,
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted source document violates Phase 1") from error


def extraction_draft_to_payload(draft: ExtractionDraft) -> dict[str, object]:
    """Serialize an extraction draft into its strict canonical JSON shape."""

    if not isinstance(draft, ExtractionDraft):
        raise DomainValidationError("draft must be an ExtractionDraft")
    if type(draft.lines) is not tuple or type(draft.evidence) is not tuple:
        raise DomainValidationError("draft collections must be immutable tuples")
    _require_canonical_sha(draft.source_sha256, "draft source_sha256")
    if not isinstance(draft.source_document_type, SourceDocumentType):
        raise DomainValidationError("draft source_document_type is invalid")

    lines: list[dict[str, object]] = []
    for line in draft.lines:
        if not isinstance(line, ExtractedLine):
            raise DomainValidationError("draft lines must contain ExtractedLine values")
        lines.append(
            {
                "sku": line.sku,
                "description": line.description,
                "quantity": _optional_decimal_to_string(line.quantity, "quantity"),
                "submitted_price": _optional_decimal_to_string(
                    line.submitted_price, "submitted_price"
                ),
            }
        )

    evidence: list[dict[str, object]] = []
    for item in draft.evidence:
        if not isinstance(item, Evidence):
            raise DomainValidationError("draft evidence must contain Evidence values")
        evidence.append(
            {
                "field_path": item.field_path,
                "source_location": item.source_location,
                "quote": item.quote,
            }
        )

    return {
        "source": {
            "sha256": draft.source_sha256,
            "document_type": draft.source_document_type.value,
        },
        "customer_name": draft.customer_name,
        "customer_reference": draft.customer_reference,
        "po_number": draft.po_number,
        "order_date": _optional_date_to_string(draft.order_date, "order_date"),
        "requested_delivery_date": _optional_date_to_string(
            draft.requested_delivery_date, "requested_delivery_date"
        ),
        "currency": draft.currency,
        "lines": lines,
        "notes": draft.notes,
        "evidence": evidence,
    }


def extraction_draft_from_payload(payload: object) -> ExtractionDraft:
    """Parse only the strict canonical JSON shape into an untrusted draft."""

    root = _require_object(payload, "payload")
    _require_exact_keys(root, _DRAFT_KEYS, "payload")
    source = _require_object(root["source"], "payload.source")
    _require_exact_keys(source, _SOURCE_KEYS, "payload.source")

    source_sha256 = _require_canonical_sha(source["sha256"], "payload.source.sha256")
    source_document_type = _source_document_type(
        source["document_type"], "payload.source.document_type"
    )
    lines_value = root["lines"]
    if type(lines_value) is not list:
        raise DomainValidationError("payload.lines must be a list")
    lines: list[ExtractedLine] = []
    for index, item in enumerate(lines_value):
        line = _require_object(item, f"payload.lines[{index}]")
        _require_exact_keys(line, _LINE_KEYS, f"payload.lines[{index}]")
        try:
            lines.append(
                ExtractedLine(
                    sku=_optional_text(line["sku"], f"payload.lines[{index}].sku"),
                    description=_optional_text(
                        line["description"], f"payload.lines[{index}].description"
                    ),
                    quantity=_optional_decimal_from_string(
                        line["quantity"], f"payload.lines[{index}].quantity"
                    ),
                    submitted_price=_optional_decimal_from_string(
                        line["submitted_price"], f"payload.lines[{index}].submitted_price"
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise DomainValidationError(f"payload.lines[{index}] is invalid") from error

    evidence_value = root["evidence"]
    if type(evidence_value) is not list:
        raise DomainValidationError("payload.evidence must be a list")
    evidence: list[Evidence] = []
    for index, item in enumerate(evidence_value):
        evidence_object = _require_object(item, f"payload.evidence[{index}]")
        _require_exact_keys(evidence_object, _EVIDENCE_KEYS, f"payload.evidence[{index}]")
        try:
            evidence.append(
                Evidence(
                    field_path=_required_text(
                        evidence_object["field_path"],
                        f"payload.evidence[{index}].field_path",
                    ),
                    source_location=_required_text(
                        evidence_object["source_location"],
                        f"payload.evidence[{index}].source_location",
                    ),
                    quote=_required_text(
                        evidence_object["quote"], f"payload.evidence[{index}].quote"
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise DomainValidationError(f"payload.evidence[{index}] is invalid") from error

    try:
        return ExtractionDraft(
            source_sha256=source_sha256,
            source_document_type=source_document_type,
            customer_name=_optional_text(root["customer_name"], "payload.customer_name"),
            customer_reference=_optional_text(
                root["customer_reference"], "payload.customer_reference"
            ),
            po_number=_optional_text(root["po_number"], "payload.po_number"),
            order_date=_optional_date_from_string(root["order_date"], "payload.order_date"),
            requested_delivery_date=_optional_date_from_string(
                root["requested_delivery_date"], "payload.requested_delivery_date"
            ),
            currency=_optional_text(root["currency"], "payload.currency"),
            lines=tuple(lines),
            notes=_optional_text(root["notes"], "payload.notes"),
            evidence=tuple(evidence),
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError(
            "payload does not satisfy the ExtractionDraft contract"
        ) from error


def extraction_snapshot_to_model(
    snapshot: PersistedExtractionSnapshot,
) -> ExtractionSnapshotModel:
    """Map a checked typed snapshot into its relational envelope."""

    if not isinstance(snapshot, PersistedExtractionSnapshot):
        raise DomainValidationError("snapshot must be a PersistedExtractionSnapshot")
    return ExtractionSnapshotModel(
        id=snapshot.id,
        order_id=snapshot.order_id,
        source_document_id=snapshot.source_document_id,
        source_sha256=snapshot.source_sha256,
        source_document_type=snapshot.source_document_type.value,
        payload=extraction_draft_to_payload(snapshot.draft),
        created_at=snapshot.created_at,
    )


def extraction_snapshot_from_model(
    row: ExtractionSnapshotModel,
) -> PersistedExtractionSnapshot:
    """Map and validate one persisted relational snapshot envelope."""

    if not isinstance(row, ExtractionSnapshotModel):
        raise DomainValidationError("row must be an ExtractionSnapshotModel")
    source_sha256 = _require_canonical_sha(row.source_sha256, "row source_sha256")
    source_document_type = _source_document_type(
        row.source_document_type, "row source_document_type"
    )
    draft = extraction_draft_from_payload(row.payload)
    try:
        return PersistedExtractionSnapshot(
            id=row.id,
            order_id=row.order_id,
            source_document_id=row.source_document_id,
            source_sha256=source_sha256,
            source_document_type=source_document_type,
            draft=draft,
            created_at=row.created_at,
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError(
            "persisted extraction snapshot violates its contract"
        ) from error


def review_revision_to_model(revision: ReviewRevision) -> ReviewRevisionModel:
    """Map a structurally valid immutable review revision to its JSONB row."""

    if not isinstance(revision, ReviewRevision):
        raise DomainValidationError("revision must be a ReviewRevision")
    return ReviewRevisionModel(
        id=revision.id,
        order_id=revision.order_id,
        extraction_snapshot_id=revision.extraction_snapshot_id,
        revision_number=revision.revision_number,
        payload=review_draft_to_payload(revision.payload),
        changes=review_changes_to_payload(revision.changes),
        actor=revision.actor,
        created_at=revision.created_at,
    )


def review_revision_from_model(row: ReviewRevisionModel) -> ReviewRevision:
    """Strictly deserialize canonical JSONB into an immutable revision."""

    if not isinstance(row, ReviewRevisionModel):
        raise DomainValidationError("row must be a ReviewRevisionModel")
    payload = review_draft_from_payload(row.payload)
    changes = review_changes_from_payload(row.changes)
    try:
        return ReviewRevision(
            id=row.id,
            order_id=row.order_id,
            extraction_snapshot_id=row.extraction_snapshot_id,
            revision_number=row.revision_number,
            payload=payload,
            changes=changes,
            actor=row.actor,
            created_at=row.created_at,
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted review revision violates its contract") from error


def _line_from_model(row: OrderLineModel, expected_order_id: UUID) -> OrderLine:
    if row.order_id != expected_order_id:
        raise DomainValidationError("order line belongs to a different order")
    quantity = _decimal_from_storage(row.quantity, "quantity")
    submitted_price = (
        _decimal_from_storage(row.submitted_price, "submitted_price")
        if row.submitted_price is not None
        else None
    )
    trusted_catalogue_price = (
        _decimal_from_storage(row.trusted_catalogue_price, "trusted_catalogue_price")
        if row.trusted_catalogue_price is not None
        else None
    )
    try:
        return OrderLine(
            id=row.id,
            sku=row.sku,
            description=row.description,
            quantity=quantity,
            submitted_price=submitted_price,
            trusted_catalogue_price=trusted_catalogue_price,
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError("persisted order line violates Phase 1") from error


def _require_object(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise DomainValidationError(f"{field_name} must be a JSON object")
    return value


def _require_exact_keys(
    value: dict[str, object], expected: frozenset[str], field_name: str
) -> None:
    if set(value) != expected:
        raise DomainValidationError(f"{field_name} has unexpected or missing keys")


def _required_text(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise DomainValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is not None and type(value) is not str:
        raise DomainValidationError(f"{field_name} must be a string or null")
    return value


def _canonical_decimal(value: Decimal, field_name: str) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainValidationError(f"{field_name} must be a finite Decimal")
    if value == 0:
        return "0"
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def _optional_decimal_to_string(value: Decimal | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _canonical_decimal(value, field_name)


def _optional_decimal_from_string(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not str or _CANONICAL_DECIMAL.fullmatch(value) is None:
        raise DomainValidationError(f"{field_name} must be a canonical Decimal string or null")
    try:
        parsed = Decimal(value)
    except (TypeError, ValueError) as error:
        raise DomainValidationError(f"{field_name} is not a Decimal string") from error
    if _canonical_decimal(parsed, field_name) != value:
        raise DomainValidationError(f"{field_name} is not canonical")
    return parsed


def _optional_date_to_string(value: date | None, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not date:
        raise DomainValidationError(f"{field_name} must be a date or null")
    return value.isoformat()


def _optional_date_from_string(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    if type(value) is not str or _CANONICAL_DATE.fullmatch(value) is None:
        raise DomainValidationError(f"{field_name} must be a canonical date string or null")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DomainValidationError(f"{field_name} is not a valid date") from error
    if parsed.isoformat() != value:
        raise DomainValidationError(f"{field_name} is not canonical")
    return parsed


def _require_canonical_sha(value: object, field_name: str) -> str:
    if type(value) is not str or _CANONICAL_SHA256.fullmatch(value) is None:
        raise DomainValidationError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _source_document_type(value: object, field_name: str) -> SourceDocumentType:
    if type(value) is not str:
        raise DomainValidationError(f"{field_name} must be a SourceDocumentType value")
    try:
        return SourceDocumentType(value)
    except ValueError as error:
        raise DomainValidationError(f"{field_name} is not a valid SourceDocumentType") from error


def _ordered_rows[ModelRow: (OrderLineModel, SourceDocumentModel)](
    rows: Sequence[ModelRow],
    expected_order_id: UUID,
    label: str,
) -> list[ModelRow]:
    positions = [row.position for row in rows]
    if any(type(position) is not int or position < 0 for position in positions):
        raise DomainValidationError(f"persisted {label} position is invalid")
    if len(positions) != len(set(positions)):
        raise DomainValidationError(f"persisted {label} positions are not unique")
    ordered = sorted(rows, key=lambda row: row.position)
    if any(row.order_id != expected_order_id for row in ordered):
        raise DomainValidationError(f"persisted {label} belongs to a different order")
    return ordered


def _metadata_from_storage(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise DomainValidationError("persisted metadata must be an outer JSON array")
    pairs: list[tuple[str, str]] = []
    for pair in value:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, str) for item in pair)
        ):
            raise DomainValidationError("persisted metadata must contain string pairs")
        pairs.append((pair[0], pair[1]))
    return tuple(pairs)


def _decimal_from_storage(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise DomainValidationError(f"persisted {field_name} must be Decimal NUMERIC data")
    return value


def _order_state(value: object, field_name: str) -> OrderState:
    try:
        return OrderState(value)
    except (TypeError, ValueError) as error:
        raise DomainValidationError(f"persisted {field_name} is not an OrderState") from error


def _require_position(position: object) -> None:
    if type(position) is not int or position < 0:
        raise DomainValidationError("position must be a non-negative integer")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must be timezone-aware")


def _require_json_value(value: object, field_name: str) -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise DomainValidationError(f"{field_name} contains a non-finite JSON number")
        return
    if isinstance(value, list):
        for item in value:
            _require_json_value(item, field_name)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise DomainValidationError(f"{field_name} contains a non-string JSON key")
        for item in value.values():
            _require_json_value(item, field_name)
        return
    raise DomainValidationError(f"{field_name} contains a non-JSON value")
