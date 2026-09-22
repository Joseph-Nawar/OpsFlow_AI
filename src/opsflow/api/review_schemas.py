"""Strict snake-case HTTP response contracts for Phase 6 review reads."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictStr

from opsflow.application.review_commands import ReviewCommandResult
from opsflow.application.review_reads import (
    ReviewDetailData,
    ReviewQueuePage,
)
from opsflow.domain import OrderState, SourceDocumentType, ValidationSeverity
from opsflow.extraction.models import ExtractionDraft
from opsflow.persistence.mappers import PersistedExtractionSnapshot
from opsflow.review import OperatorRole, ReviewChange, ReviewDraft, ReviewLine, ReviewRevision
from opsflow.validation import TrustedBusinessData


class ReviewQueueItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    state: OrderState
    failure_origin: OrderState | None
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    created_at: datetime
    validation_issue_count: int
    high_value_approval_required: bool


class ReviewQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReviewQueueItemResponse]
    states: list[OrderState]
    limit: int
    offset: int
    total: int


class ReviewLineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None
    description: str | None
    quantity: Decimal | None
    submitted_price: Decimal | None


class ReviewLineRequest(BaseModel):
    """One editable untrusted line; trusted catalogue values are not accepted."""

    model_config = ConfigDict(extra="forbid")

    sku: StrictStr | None
    description: StrictStr | None
    quantity: Decimal | None
    submitted_price: Decimal | None


class ReviewDraftRequest(BaseModel):
    """Complete strict HTTP candidate containing editable review values only."""

    model_config = ConfigDict(extra="forbid")

    customer_name: StrictStr | None
    customer_reference: StrictStr | None
    po_number: StrictStr | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: StrictStr | None
    lines: list[ReviewLineRequest]

    def to_contract(self) -> ReviewDraft:
        """Convert mutable transport arrays to the immutable application value."""

        return ReviewDraft(
            customer_name=self.customer_name,
            customer_reference=self.customer_reference,
            po_number=self.po_number,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            currency=self.currency,
            lines=tuple(
                ReviewLine(
                    sku=line.sku,
                    description=line.description,
                    quantity=line.quantity,
                    submitted_price=line.submitted_price,
                )
                for line in self.lines
            ),
        )


class ReviewDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str | None
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    lines: list[ReviewLineResponse]
    source_snapshot_id: UUID | None = None
    latest_revision_number: int | None = None


class ExtractionLineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None
    description: str | None
    quantity: Decimal | None
    submitted_price: Decimal | None


class ExtractionEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    source_location: str | None
    quote: str | None


class OriginalExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sha256: str
    source_document_type: SourceDocumentType
    customer_name: str | None
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    lines: list[ExtractionLineResponse]
    notes: str | None
    evidence: list[ExtractionEvidenceResponse]


class ReviewSourceSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    source_document_id: UUID
    source_sha256: str
    source_document_type: SourceDocumentType
    created_at: datetime


class ReviewChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    old_value: Any
    new_value: Any


class ReviewRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    revision_number: int
    actor: str
    created_at: datetime
    changes: list[ReviewChangeResponse]


class ReviewTrustedLineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    sku: str | None
    description: str | None
    quantity: Decimal
    submitted_price: Decimal | None
    trusted_catalogue_price: Decimal | None


class ReviewTrustedOrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    state: OrderState
    failure_origin: OrderState | None
    created_at: datetime
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    lines: list[ReviewTrustedLineResponse]


class ReviewValidationIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_code: str
    severity: ValidationSeverity
    field: str | None
    expected: Any | None
    actual: Any | None
    explanation: str


class ReviewSourceDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None
    storage_reference: str | None
    metadata: list[ReviewMetadataPairResponse]


class ReviewMetadataPairResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: str


class ReviewActionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_edit: bool
    can_approve: bool
    can_reject: bool
    can_retry: bool


class ReviewOperatorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str
    role: OperatorRole


class ReviewDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    etag: str
    order: ReviewTrustedOrderResponse
    source_documents: list[ReviewSourceDocumentResponse]
    source_snapshot: ReviewSourceSnapshotResponse | None
    original_extraction: OriginalExtractionResponse | None
    effective_draft: ReviewDraftResponse | None
    revisions: list[ReviewRevisionResponse]
    latest_revision: ReviewRevisionResponse | None
    validation_issues: list[ReviewValidationIssueResponse]
    operator: ReviewOperatorResponse
    actions: ReviewActionsResponse


class ReferenceCustomerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str
    name: str
    active: bool


class ReferenceProductResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    description: str | None
    active: bool
    currency: str
    catalogue_price: Decimal | None
    available_quantity: Decimal | None


class ReviewReferenceDataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    customer_candidates: list[ReferenceCustomerResponse]
    products_by_line: list[ReferenceProductResponse | None]


class ReviewRejectRequest(BaseModel):
    """Strict command body containing only the operator's bounded reason."""

    model_config = ConfigDict(extra="forbid")

    reason: StrictStr


class ReviewCommandResponse(BaseModel):
    """Narrow result emitted after one review lifecycle command commits."""

    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    etag: StrictStr


def review_queue_response(page: ReviewQueuePage) -> ReviewQueueResponse:
    return ReviewQueueResponse(
        items=[
            ReviewQueueItemResponse(
                id=item.id,
                state=item.state,
                failure_origin=item.failure_origin,
                customer_reference=item.customer_reference,
                po_number=item.po_number,
                order_date=item.order_date,
                requested_delivery_date=item.requested_delivery_date,
                currency=item.currency,
                created_at=item.created_at,
                validation_issue_count=item.validation_issue_count,
                high_value_approval_required=item.high_value_approval_required,
            )
            for item in page.items
        ],
        states=list(page.states),
        limit=page.limit,
        offset=page.offset,
        total=page.total,
    )


def review_detail_response(detail: ReviewDetailData) -> ReviewDetailResponse:
    persisted = detail.order
    order = persisted.order
    snapshot = detail.source_snapshot
    latest = detail.latest_revision
    return ReviewDetailResponse(
        etag=detail.etag,
        order=ReviewTrustedOrderResponse(
            id=order.id,
            state=order.state,
            failure_origin=order.failure_origin,
            created_at=persisted.created_at,
            customer_reference=order.customer_reference,
            po_number=order.po_number,
            order_date=order.order_date,
            requested_delivery_date=order.requested_delivery_date,
            currency=order.currency,
            lines=[
                ReviewTrustedLineResponse(
                    id=line.id,
                    sku=line.sku,
                    description=line.description,
                    quantity=line.quantity,
                    submitted_price=line.submitted_price,
                    trusted_catalogue_price=line.trusted_catalogue_price,
                )
                for line in order.lines
            ],
        ),
        source_documents=[
            ReviewSourceDocumentResponse(
                id=document.id,
                document_type=document.document_type,
                name=document.name,
                mime_type=document.mime_type,
                sha256=document.sha256,
                message_id=document.message_id,
                storage_reference=document.storage_reference,
                metadata=[
                    ReviewMetadataPairResponse(key=key, value=value)
                    for key, value in document.metadata
                ],
            )
            for document in order.source_documents
        ],
        source_snapshot=(
            ReviewSourceSnapshotResponse(
                id=snapshot.id,
                source_document_id=snapshot.source_document_id,
                source_sha256=snapshot.source_sha256,
                source_document_type=snapshot.source_document_type,
                created_at=snapshot.created_at,
            )
            if snapshot is not None
            else None
        ),
        original_extraction=(
            _original_extraction(snapshot.draft) if snapshot is not None else None
        ),
        effective_draft=(
            _effective_draft(detail.effective_draft, snapshot, latest)
            if detail.effective_draft is not None
            else None
        ),
        revisions=[_revision_response(revision) for revision in detail.revisions],
        latest_revision=_revision_response(latest) if latest is not None else None,
        validation_issues=[
            ReviewValidationIssueResponse(
                rule_code=issue.rule_code,
                severity=issue.severity,
                field=issue.field,
                expected=issue.expected,
                actual=issue.actual,
                explanation=issue.explanation,
            )
            for issue in persisted.validation_issues
        ],
        operator=ReviewOperatorResponse(
            actor=detail.operator.actor,
            role=detail.operator.role,
        ),
        actions=ReviewActionsResponse(
            can_edit=detail.actions.can_edit,
            can_approve=detail.actions.can_approve,
            can_reject=detail.actions.can_reject,
            can_retry=detail.actions.can_retry,
        ),
    )


def reference_data_response(data: TrustedBusinessData) -> ReviewReferenceDataResponse:
    return ReviewReferenceDataResponse(
        label="Current trusted reference data",
        customer_candidates=[
            ReferenceCustomerResponse(
                reference=item.reference,
                name=item.name,
                active=item.active,
            )
            for item in data.customer_candidates
        ],
        products_by_line=[
            (
                ReferenceProductResponse(
                    sku=item.sku,
                    description=item.description,
                    active=item.active,
                    currency=item.currency,
                    catalogue_price=item.catalogue_price,
                    available_quantity=item.available_quantity,
                )
                if item is not None
                else None
            )
            for item in data.products_by_line
        ],
    )


def review_command_response(result: ReviewCommandResult) -> ReviewCommandResponse:
    """Map the committed application result without adding review or audit data."""

    return ReviewCommandResponse(
        order_id=result.order_id,
        state=result.state,
        failure_origin=result.failure_origin,
        etag=result.etag,
    )


def _effective_draft(
    draft: ReviewDraft,
    snapshot: PersistedExtractionSnapshot | None,
    latest: ReviewRevision | None,
) -> ReviewDraftResponse:
    return ReviewDraftResponse(
        customer_name=draft.customer_name,
        customer_reference=draft.customer_reference,
        po_number=draft.po_number,
        order_date=draft.order_date,
        requested_delivery_date=draft.requested_delivery_date,
        currency=draft.currency,
        lines=[
            ReviewLineResponse(
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                submitted_price=line.submitted_price,
            )
            for line in draft.lines
        ],
        source_snapshot_id=snapshot.id if snapshot is not None else None,
        latest_revision_number=latest.revision_number if latest is not None else None,
    )


def _original_extraction(draft: ExtractionDraft) -> OriginalExtractionResponse:
    return OriginalExtractionResponse(
        source_sha256=draft.source_sha256,
        source_document_type=draft.source_document_type,
        customer_name=draft.customer_name,
        customer_reference=draft.customer_reference,
        po_number=draft.po_number,
        order_date=draft.order_date,
        requested_delivery_date=draft.requested_delivery_date,
        currency=draft.currency,
        lines=[
            ExtractionLineResponse(
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                submitted_price=line.submitted_price,
            )
            for line in draft.lines
        ],
        notes=draft.notes,
        evidence=[
            ExtractionEvidenceResponse(
                field_path=item.field_path,
                source_location=item.source_location,
                quote=item.quote,
            )
            for item in draft.evidence
        ],
    )


def _revision_response(revision: ReviewRevision) -> ReviewRevisionResponse:
    return ReviewRevisionResponse(
        id=revision.id,
        revision_number=revision.revision_number,
        actor=revision.actor,
        created_at=revision.created_at,
        changes=[_change_response(change) for change in revision.changes],
    )


def _change_response(change: ReviewChange) -> ReviewChangeResponse:
    return ReviewChangeResponse(
        field_path=change.field_path,
        old_value=change.old_value,
        new_value=change.new_value,
    )
