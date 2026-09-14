"""Explicit conversion between Phase 1 records and persistence models."""

from collections.abc import Sequence
from datetime import datetime
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

from .models import (
    AuditEventModel,
    OrderLineModel,
    OrderModel,
    SourceDocumentModel,
    ValidationIssueModel,
)


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
