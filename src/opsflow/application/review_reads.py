"""Read-only application projections for the Phase 6 human-review queue."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
    OrderNotFoundError,
    ReviewCaseUnavailableError,
    ReviewDraftUnavailableError,
)
from opsflow.domain import DomainValidationError, OrderState, ValidationSeverity
from opsflow.persistence.mappers import PersistedExtractionSnapshot
from opsflow.persistence.repositories import (
    PersistedOrder,
    ReviewOrderSummary,
    get_extraction_snapshots_for_order,
    get_latest_audit_event_id,
    get_latest_review_revision,
    get_order,
    get_review_revision_history,
    list_review_order_summaries,
)
from opsflow.review import (
    OperatorContext,
    OperatorRole,
    ReviewDraft,
    ReviewRevision,
)
from opsflow.review.auth import require_view_access
from opsflow.review.concurrency import compute_review_etag
from opsflow.review.serialization import (
    compose_extraction_draft,
    project_effective_review_draft,
    review_draft_from_extraction,
)
from opsflow.validation import BusinessDataLookupRequest, TrustedBusinessData
from opsflow.validation.business_data import (
    BusinessDataProvider,
    TrustedBusinessDataContractError,
    validate_trusted_business_data,
)

_QUEUE_STATES = (
    OrderState.NEEDS_REVIEW,
    OrderState.READY_FOR_APPROVAL,
    OrderState.FAILED_RETRYABLE,
)


@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    """One bounded queue item and persisted validation signal projection."""

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


@dataclass(frozen=True, slots=True)
class ReviewQueuePage:
    """One deterministic page from the supported operational review states."""

    items: tuple[ReviewQueueItem, ...]
    states: tuple[OrderState, ...]
    limit: int
    offset: int
    total: int


@dataclass(frozen=True, slots=True)
class ReviewActions:
    """Backend-computed actions permitted for one operator and current order."""

    can_edit: bool
    can_approve: bool
    can_reject: bool
    can_retry: bool


@dataclass(frozen=True, slots=True)
class ReviewDetailData:
    """Stable database-backed review detail and its concurrency validator."""

    order: PersistedOrder
    source_snapshot: PersistedExtractionSnapshot | None
    effective_draft: ReviewDraft | None
    revisions: tuple[ReviewRevision, ...]
    latest_revision: ReviewRevision | None
    actions: ReviewActions
    operator: OperatorContext
    etag: str


async def list_review_orders(
    session: AsyncSession,
    states: tuple[OrderState, ...] | None,
    limit: int,
    offset: int,
    operator: OperatorContext,
) -> ReviewQueuePage:
    """Return a bounded oldest-first page for an authorized review operator."""

    require_view_access(operator)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be nonnegative")
    selected_states = _normalize_queue_states(states)
    rows, total = await list_review_order_summaries(session, selected_states, limit, offset)
    return ReviewQueuePage(
        items=tuple(_queue_item(row) for row in rows),
        states=selected_states,
        limit=limit,
        offset=offset,
        total=total,
    )


async def get_review_detail(
    session: AsyncSession,
    order_id: UUID,
    operator: OperatorContext,
) -> ReviewDetailData:
    """Load a stable review case, effective draft, actions, and strong ETag."""

    require_view_access(operator)
    try:
        persisted = await get_order(session, order_id)
        if persisted is None:
            raise OrderNotFoundError(order_id)
        snapshots = await get_extraction_snapshots_for_order(session, order_id)
        latest = await get_latest_review_revision(session, order_id)
        revisions = await get_review_revision_history(session, order_id)
        latest_audit_id = await get_latest_audit_event_id(session, order_id)
        snapshot, effective_draft = _resolve_effective_draft(
            persisted,
            snapshots,
            latest,
            revisions,
        )
    except DomainValidationError:
        raise ReviewCaseUnavailableError() from None

    high_value = any(
        issue.rule_code == "HIGH_VALUE_APPROVAL_REQUIRED"
        and issue.severity is ValidationSeverity.WARNING
        for issue in persisted.validation_issues
    )
    actions = _actions_for(persisted.order.state, operator.role, high_value)
    etag = compute_review_etag(
        persisted.order.id,
        persisted.order.state,
        persisted.order.failure_origin,
        latest.revision_number if latest is not None else None,
        latest.id if latest is not None else None,
        latest_audit_id,
    )
    return ReviewDetailData(
        order=persisted,
        source_snapshot=snapshot,
        effective_draft=effective_draft,
        revisions=revisions,
        latest_revision=latest,
        actions=actions,
        operator=operator,
        etag=etag,
    )


async def get_current_reference_data(
    session: AsyncSession,
    order_id: UUID,
    operator: OperatorContext,
    provider: BusinessDataProvider,
) -> TrustedBusinessData:
    """Read an effective draft, close its transaction, then query trusted data."""

    require_view_access(operator)
    try:
        persisted = await get_order(session, order_id)
        if persisted is None:
            raise OrderNotFoundError(order_id)
        snapshots = await get_extraction_snapshots_for_order(session, order_id)
        latest = await get_latest_review_revision(session, order_id)
        snapshot, effective_draft = _resolve_effective_draft(
            persisted,
            snapshots,
            latest,
            (),
            history_loaded=False,
        )
        if snapshot is None or effective_draft is None:
            raise ReviewDraftUnavailableError()
        candidate = compose_extraction_draft(snapshot.draft, effective_draft)
    except DomainValidationError:
        await session.rollback()
        raise ReviewCaseUnavailableError() from None
    except Exception:
        await session.rollback()
        raise
    await session.rollback()
    if session.in_transaction():
        raise AssertionError("reference provider boundary requires a closed database transaction")

    lookup = BusinessDataLookupRequest(
        customer_reference=candidate.customer_reference,
        customer_name=(
            None if candidate.customer_reference is not None else candidate.customer_name
        ),
        skus=tuple(line.sku for line in candidate.lines),
    )
    try:
        result = await provider.get_validation_data(lookup)
    except Exception:
        raise BusinessDataProviderError() from None
    try:
        validate_trusted_business_data(candidate, result)
    except TrustedBusinessDataContractError:
        raise InvalidTrustedDataError() from None
    return result


def _normalize_queue_states(states: tuple[OrderState, ...] | None) -> tuple[OrderState, ...]:
    if states is None or states == ():
        return _QUEUE_STATES
    if type(states) is not tuple or not all(isinstance(state, OrderState) for state in states):
        raise ValueError("states must be an immutable tuple of supported order states")
    if len(set(states)) != len(states) or any(state not in _QUEUE_STATES for state in states):
        raise ValueError("states contain a duplicate or unsupported review queue state")
    return states


def _queue_item(row: ReviewOrderSummary) -> ReviewQueueItem:
    return ReviewQueueItem(
        id=row.id,
        state=row.state,
        failure_origin=row.failure_origin,
        customer_reference=row.customer_reference,
        po_number=row.po_number,
        order_date=row.order_date,
        requested_delivery_date=row.requested_delivery_date,
        currency=row.currency,
        created_at=row.created_at,
        validation_issue_count=row.validation_issue_count,
        high_value_approval_required=row.high_value_approval_required,
    )


def _resolve_effective_draft(
    persisted: PersistedOrder,
    snapshots: tuple[PersistedExtractionSnapshot, ...],
    latest: ReviewRevision | None,
    revisions: tuple[ReviewRevision, ...],
    *,
    history_loaded: bool = True,
) -> tuple[PersistedExtractionSnapshot | None, ReviewDraft | None]:
    order = persisted.order
    if len(snapshots) == 0:
        if (
            order.state is not OrderState.FAILED_RETRYABLE
            or order.failure_origin not in (OrderState.PROCESSING, OrderState.EXTRACTED)
            or latest is not None
            or revisions
        ):
            raise ReviewCaseUnavailableError()
        return None, None
    if len(snapshots) != 1:
        raise ReviewCaseUnavailableError()

    snapshot = snapshots[0]
    if snapshot.order_id != order.id:
        raise ReviewCaseUnavailableError()
    source = next(
        (
            document
            for document in order.source_documents
            if document.id == snapshot.source_document_id
        ),
        None,
    )
    if (
        source is None
        or source.sha256.casefold() != snapshot.source_sha256
        or source.document_type is not snapshot.source_document_type
    ):
        raise ReviewCaseUnavailableError()
    if order.state is OrderState.FAILED_RETRYABLE and order.failure_origin in (
        OrderState.PROCESSING,
        OrderState.EXTRACTED,
    ):
        raise ReviewCaseUnavailableError()
    if latest is not None and (
        latest.order_id != order.id or latest.extraction_snapshot_id != snapshot.id
    ):
        raise ReviewCaseUnavailableError()
    if history_loaded:
        if revisions and (
            revisions[-1] != latest
            or tuple(item.revision_number for item in revisions)
            != tuple(sorted({item.revision_number for item in revisions}))
        ):
            raise ReviewCaseUnavailableError()
        if any(
            item.order_id != order.id or item.extraction_snapshot_id != snapshot.id
            for item in revisions
        ):
            raise ReviewCaseUnavailableError()
        if latest is None and revisions:
            raise ReviewCaseUnavailableError()
    original = review_draft_from_extraction(snapshot.draft)
    return snapshot, project_effective_review_draft(original, latest)


def _actions_for(state: OrderState, role: OperatorRole, high_value: bool) -> ReviewActions:
    return ReviewActions(
        can_edit=role is OperatorRole.REVIEWER and state is OrderState.NEEDS_REVIEW,
        can_approve=(
            state is OrderState.READY_FOR_APPROVAL
            and (
                role is OperatorRole.ELEVATED_APPROVER
                or (role is OperatorRole.APPROVER and not high_value)
            )
        ),
        can_reject=(
            (role is OperatorRole.REVIEWER and state is OrderState.NEEDS_REVIEW)
            or (
                role in (OperatorRole.APPROVER, OperatorRole.ELEVATED_APPROVER)
                and state is OrderState.READY_FOR_APPROVAL
            )
        ),
        can_retry=role is OperatorRole.REVIEWER and state is OrderState.FAILED_RETRYABLE,
    )
