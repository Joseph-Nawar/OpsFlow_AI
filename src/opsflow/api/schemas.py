"""Pydantic transport contracts and explicit domain response mappings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opsflow.application.orders import (
    CreateLineInput,
    CreateOrderInput,
    CreateSourceDocumentInput,
)
from opsflow.domain import (
    AuditEvent,
    OrderState,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.persistence.repositories import OrderSummary, PersistedOrder


class MetadataPair(BaseModel):
    """One ordered source-document metadata pair."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str


class OrderLineCreate(BaseModel):
    """Transport fields for one client-supplied order line."""

    model_config = ConfigDict(extra="forbid")

    sku: str | None = None
    description: str | None = None
    quantity: Decimal
    submitted_price: Decimal | None = None
    trusted_catalogue_price: Decimal | None = None


class SourceDocumentCreate(BaseModel):
    """Transport fields for one client-supplied document reference."""

    model_config = ConfigDict(extra="forbid")

    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None = None
    storage_reference: str | None = None
    metadata: list[MetadataPair] = Field(default_factory=list)


class OrderCreateRequest(BaseModel):
    """Allowed client-owned values for order intake."""

    model_config = ConfigDict(extra="forbid")

    customer_reference: str | None = None
    po_number: str | None = None
    order_date: date | None = None
    requested_delivery_date: date | None = None
    currency: str | None = None
    lines: list[OrderLineCreate] = Field(default_factory=list)
    source_documents: list[SourceDocumentCreate] = Field(default_factory=list)


class OrderLineResponse(BaseModel):
    """Serialized persisted order-line data."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    sku: str | None
    description: str | None
    quantity: Decimal
    submitted_price: Decimal | None
    trusted_catalogue_price: Decimal | None


class SourceDocumentResponse(BaseModel):
    """Serialized persisted source-document metadata."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None
    storage_reference: str | None
    metadata: list[MetadataPair]


class ValidationIssueResponse(BaseModel):
    """Serialized persisted validation issue data."""

    model_config = ConfigDict(extra="forbid")

    rule_code: str
    severity: ValidationSeverity
    field: str | None
    expected: Any | None
    actual: Any | None
    explanation: str


class OrderDetailResponse(BaseModel):
    """Full order response without embedded audit history."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    state: OrderState
    failure_origin: OrderState | None
    created_at: datetime
    lines: list[OrderLineResponse]
    source_documents: list[SourceDocumentResponse]
    validation_issues: list[ValidationIssueResponse]


class OrderSummaryResponse(BaseModel):
    """Lightweight list item containing only approved summary fields."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    state: OrderState
    created_at: datetime


class OrderListResponse(BaseModel):
    """Paginated order summaries."""

    model_config = ConfigDict(extra="forbid")

    items: list[OrderSummaryResponse]
    limit: int
    offset: int
    total: int


class AuditEventResponse(BaseModel):
    """Serialized audit event response."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    order_id: UUID
    event_type: str
    actor: str
    occurred_at: datetime
    description: str


class AuditListResponse(BaseModel):
    """Ordered audit history kept separate from order detail."""

    model_config = ConfigDict(extra="forbid")

    items: list[AuditEventResponse]


def to_create_order_input(request: OrderCreateRequest) -> CreateOrderInput:
    """Map validated transport values to immutable application input."""

    return CreateOrderInput(
        customer_reference=request.customer_reference,
        po_number=request.po_number,
        order_date=request.order_date,
        requested_delivery_date=request.requested_delivery_date,
        currency=request.currency,
        lines=tuple(
            CreateLineInput(
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                submitted_price=line.submitted_price,
                trusted_catalogue_price=line.trusted_catalogue_price,
            )
            for line in request.lines
        ),
        source_documents=tuple(
            CreateSourceDocumentInput(
                document_type=document.document_type,
                name=document.name,
                mime_type=document.mime_type,
                sha256=document.sha256,
                message_id=document.message_id,
                storage_reference=document.storage_reference,
                metadata=tuple((pair.key, pair.value) for pair in document.metadata),
            )
            for document in request.source_documents
        ),
    )


def order_detail_response(persisted: PersistedOrder) -> OrderDetailResponse:
    """Map a persistence read container to a dedicated detail response."""

    order = persisted.order
    return OrderDetailResponse(
        id=order.id,
        customer_reference=order.customer_reference,
        po_number=order.po_number,
        order_date=order.order_date,
        requested_delivery_date=order.requested_delivery_date,
        currency=order.currency,
        state=order.state,
        failure_origin=order.failure_origin,
        created_at=persisted.created_at,
        lines=[
            OrderLineResponse(
                id=line.id,
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                submitted_price=line.submitted_price,
                trusted_catalogue_price=line.trusted_catalogue_price,
            )
            for line in order.lines
        ],
        source_documents=[
            SourceDocumentResponse(
                id=document.id,
                document_type=document.document_type,
                name=document.name,
                mime_type=document.mime_type,
                sha256=document.sha256,
                message_id=document.message_id,
                storage_reference=document.storage_reference,
                metadata=[MetadataPair(key=key, value=value) for key, value in document.metadata],
            )
            for document in order.source_documents
        ],
        validation_issues=[
            ValidationIssueResponse(
                rule_code=issue.rule_code,
                severity=issue.severity,
                field=issue.field,
                expected=issue.expected,
                actual=issue.actual,
                explanation=issue.explanation,
            )
            for issue in persisted.validation_issues
        ],
    )


def order_summary_response(summary: OrderSummary) -> OrderSummaryResponse:
    """Map one typed repository summary to its response schema."""

    return OrderSummaryResponse(
        id=summary.id,
        customer_reference=summary.customer_reference,
        po_number=summary.po_number,
        order_date=summary.order_date,
        requested_delivery_date=summary.requested_delivery_date,
        currency=summary.currency,
        state=summary.state,
        created_at=summary.created_at,
    )


def audit_event_response(event: AuditEvent) -> AuditEventResponse:
    """Map one domain audit event to its response schema."""

    return AuditEventResponse(
        id=event.id,
        order_id=event.order_id,
        event_type=event.event_type,
        actor=event.actor,
        occurred_at=event.occurred_at,
        description=event.description,
    )


def validation_issue_response(issue: ValidationIssue) -> ValidationIssueResponse:
    """Map one domain validation issue to its response schema."""

    return ValidationIssueResponse(
        rule_code=issue.rule_code,
        severity=issue.severity,
        field=issue.field,
        expected=issue.expected,
        actual=issue.actual,
        explanation=issue.explanation,
    )
