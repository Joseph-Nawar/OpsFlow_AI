"""Save & revalidate application operation for human-reviewed candidates."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidReviewStateError,
    InvalidTrustedDataError,
    NoReviewChangesError,
    OrderNotFoundError,
    ReviewCaseUnavailableError,
    ReviewPersistenceConflictError,
    ValidationFactsChangedError,
)
from opsflow.domain import AuditEvent, DomainValidationError, Order, OrderState
from opsflow.extraction.models import ExtractionDraft
from opsflow.notifications.contracts import NotificationChannel, NotificationKind
from opsflow.notifications.service import create_notification_intent
from opsflow.persistence.mappers import PersistedExtractionSnapshot
from opsflow.persistence.repositories import (
    PersistedOrder,
    build_validation_facts,
    get_extraction_snapshots_for_order,
    get_latest_audit_event_id,
    get_latest_review_revision,
    get_order,
    get_order_for_update,
    insert_audit_event,
    insert_review_revision,
    replace_order_graph,
    replace_validation_issues,
    update_order_snapshot,
)
from opsflow.review import OperatorContext, ReviewChange, ReviewDraft, ReviewRevision
from opsflow.review.auth import require_reviewer
from opsflow.review.composition import ReviewDateProvider
from opsflow.review.concurrency import compute_review_etag, require_if_match
from opsflow.review.serialization import (
    compose_extraction_draft,
    compute_review_changes,
    project_effective_review_draft,
    review_draft_from_extraction,
)
from opsflow.validation import (
    ApprovalLevel,
    BusinessDataLookupRequest,
    TrustedBusinessData,
    ValidatedOrderData,
    ValidationContext,
    ValidationResult,
    ValidationRoute,
)
from opsflow.validation import engine as validation_engine
from opsflow.validation.business_data import (
    BusinessDataProvider,
    TrustedBusinessDataContractError,
    validate_trusted_business_data,
)
from opsflow.validation.policy import ValidationPolicy


@dataclass(frozen=True, slots=True)
class ReviewRevalidationResult:
    """Committed result and fresh concurrency validator for one revalidation."""

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    revision_id: UUID
    revision_number: int
    validation_result: ValidationResult
    etag: str


@dataclass(frozen=True, slots=True)
class _ReviewPreflight:
    snapshot: PersistedExtractionSnapshot
    changes: tuple[ReviewChange, ...]
    candidate_extraction: ExtractionDraft


async def save_and_revalidate(
    session: AsyncSession,
    order_id: UUID,
    candidate: ReviewDraft,
    if_match: str | None,
    operator: OperatorContext,
    provider: BusinessDataProvider,
    policy: ValidationPolicy,
    date_provider: ReviewDateProvider,
    recorded_at: datetime,
    review_base_url: str,
) -> ReviewRevalidationResult:
    """Validate a changed human candidate, then atomically persist its result."""

    require_reviewer(operator)
    evaluation_date = date_provider.current_date()
    context = ValidationContext(evaluation_date=evaluation_date)
    _require_aware_recorded_at(recorded_at)
    if not isinstance(candidate, ReviewDraft):
        raise DomainValidationError("candidate must be a ReviewDraft")

    try:
        preflight = await _load_preflight(session, order_id, candidate, if_match)
    except Exception:
        await session.rollback()
        raise
    await session.rollback()
    _require_closed_transaction(session, "preflight rollback")

    trusted_data = await _load_trusted_data(provider, preflight.candidate_extraction)
    customer_reference = canonical_customer_reference(trusted_data)

    try:
        facts = await build_validation_facts(
            session,
            order_id=order_id,
            source_document_id=preflight.snapshot.source_document_id,
            canonical_customer_reference=customer_reference,
            po_number=candidate.po_number,
            source_sha256=preflight.snapshot.source_sha256,
        )
    except Exception:
        await session.rollback()
        raise
    await session.rollback()
    _require_closed_transaction(session, "validation-facts rollback")

    validation_result = validation_engine.validate(
        preflight.candidate_extraction,
        trusted_data,
        facts,
        policy,
        context,
    )
    if validation_result.route is ValidationRoute.READY_FOR_APPROVAL and not isinstance(
        validation_result.validated_order_data, ValidatedOrderData
    ):
        raise InvalidTrustedDataError()

    revision: ReviewRevision | None = None
    audit_events: tuple[AuditEvent, ...]
    final_order: Order
    try:
        async with session.begin():
            locked = await get_order_for_update(session, order_id)
            if locked is None:
                raise OrderNotFoundError(order_id)
            if locked.order.state is not OrderState.NEEDS_REVIEW:
                raise InvalidReviewStateError()

            snapshots = await get_extraction_snapshots_for_order(session, order_id)
            latest_revision = await get_latest_review_revision(session, order_id)
            latest_audit_id = await get_latest_audit_event_id(session, order_id)
            snapshot = _require_review_snapshot(locked, snapshots, latest_revision)
            if snapshot != preflight.snapshot:
                raise ReviewCaseUnavailableError()

            current_etag = _review_etag(locked.order, latest_revision, latest_audit_id)
            require_if_match(if_match, current_etag)

            fresh_facts = await build_validation_facts(
                session,
                order_id=order_id,
                source_document_id=snapshot.source_document_id,
                canonical_customer_reference=customer_reference,
                po_number=candidate.po_number,
                source_sha256=snapshot.source_sha256,
            )
            if fresh_facts != facts:
                raise ValidationFactsChangedError(order_id)

            revision = ReviewRevision(
                id=uuid4(),
                order_id=order_id,
                extraction_snapshot_id=snapshot.id,
                revision_number=(latest_revision.revision_number + 1 if latest_revision else 1),
                payload=candidate,
                changes=preflight.changes,
                actor=operator.actor,
                created_at=recorded_at,
            )
            await insert_review_revision(session, revision)
            await replace_validation_issues(session, order_id, validation_result.issues)

            if validation_result.route is ValidationRoute.READY_FOR_APPROVAL:
                validated = validation_result.validated_order_data
                if not isinstance(validated, ValidatedOrderData):
                    raise InvalidTrustedDataError()
                line_ids = tuple(uuid4() for _ in validated.lines)
                promoted = locked.order.promote_reviewed_data(validated, line_ids)
                final_order = promoted.transition_to(OrderState.VALIDATED).transition_to(
                    OrderState.READY_FOR_APPROVAL
                )
                await update_order_snapshot(session, final_order)
                await replace_order_graph(session, final_order)
            else:
                final_order = locked.order.transition_to(OrderState.VALIDATED).transition_to(
                    OrderState.NEEDS_REVIEW
                )
                await update_order_snapshot(session, final_order)

            audit_events = _audit_events(
                order_id,
                operator,
                validation_result,
                recorded_at,
            )
            for event in audit_events:
                await insert_audit_event(session, event)
            await create_notification_intent(
                session,
                order=final_order,
                event=audit_events[-1],
                channel=NotificationChannel.SLACK,
                kind=(
                    NotificationKind.APPROVAL_READY
                    if validation_result.route is ValidationRoute.READY_FOR_APPROVAL
                    else NotificationKind.REVIEW_REQUIRED
                ),
                review_base_url=review_base_url,
                issues=validation_result.issues,
            )
    except IntegrityError:
        raise ReviewPersistenceConflictError() from None

    if revision is None:
        raise AssertionError("a committed revalidation must have a review revision")
    fresh_etag = _review_etag(
        final_order,
        revision,
        audit_events[-1].id,
    )
    return ReviewRevalidationResult(
        order_id=order_id,
        state=final_order.state,
        failure_origin=final_order.failure_origin,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        validation_result=validation_result,
        etag=fresh_etag,
    )


def canonical_customer_reference(trusted_data: TrustedBusinessData) -> str | None:
    """Return an unambiguous active customer identity for local duplicate facts."""

    if len(trusted_data.customer_candidates) != 1:
        return None
    candidate = trusted_data.customer_candidates[0]
    if not candidate.active:
        return None
    return candidate.reference


async def _load_preflight(
    session: AsyncSession,
    order_id: UUID,
    candidate: ReviewDraft,
    if_match: str | None,
) -> _ReviewPreflight:
    persisted = await get_order(session, order_id)
    if persisted is None:
        raise OrderNotFoundError(order_id)
    snapshots = await get_extraction_snapshots_for_order(session, order_id)
    latest_revision = await get_latest_review_revision(session, order_id)
    latest_audit_id = await get_latest_audit_event_id(session, order_id)
    snapshot = _require_review_snapshot(persisted, snapshots, latest_revision)
    current_etag = _review_etag(persisted.order, latest_revision, latest_audit_id)
    require_if_match(if_match, current_etag)
    if persisted.order.state is not OrderState.NEEDS_REVIEW:
        raise InvalidReviewStateError()

    effective_draft = project_effective_review_draft(
        review_draft_from_extraction(snapshot.draft),
        latest_revision,
    )
    changes = compute_review_changes(effective_draft, candidate)
    if not changes:
        raise NoReviewChangesError()
    candidate_extraction = compose_extraction_draft(snapshot.draft, candidate)
    return _ReviewPreflight(
        snapshot=snapshot,
        changes=changes,
        candidate_extraction=candidate_extraction,
    )


def _require_review_snapshot(
    persisted: PersistedOrder,
    snapshots: tuple[PersistedExtractionSnapshot, ...],
    latest_revision: ReviewRevision | None,
) -> PersistedExtractionSnapshot:
    if len(snapshots) != 1:
        raise ReviewCaseUnavailableError()
    snapshot = snapshots[0]
    if snapshot.order_id != persisted.order.id:
        raise ReviewCaseUnavailableError()

    source = next(
        (
            document
            for document in persisted.order.source_documents
            if document.id == snapshot.source_document_id
        ),
        None,
    )
    if source is None:
        raise ReviewCaseUnavailableError()
    if (
        source.sha256.casefold() != snapshot.source_sha256
        or source.document_type is not snapshot.source_document_type
        or snapshot.draft.source_sha256 != snapshot.source_sha256
        or snapshot.draft.source_document_type is not snapshot.source_document_type
    ):
        raise ReviewCaseUnavailableError()
    if latest_revision is not None and (
        latest_revision.order_id != persisted.order.id
        or latest_revision.extraction_snapshot_id != snapshot.id
    ):
        raise ReviewCaseUnavailableError()
    return snapshot


async def _load_trusted_data(
    provider: BusinessDataProvider,
    candidate: ExtractionDraft,
) -> TrustedBusinessData:
    lookup = BusinessDataLookupRequest(
        customer_reference=candidate.customer_reference,
        customer_name=(
            None if candidate.customer_reference is not None else candidate.customer_name
        ),
        skus=tuple(line.sku for line in candidate.lines),
    )
    try:
        result = await provider.get_validation_data(lookup)
        validate_trusted_business_data(candidate, result)
    except TrustedBusinessDataContractError:
        raise InvalidTrustedDataError() from None
    except Exception:
        raise BusinessDataProviderError() from None
    return result


def _review_etag(
    order: Order,
    latest_revision: ReviewRevision | None,
    latest_audit_id: UUID | None,
) -> str:
    return compute_review_etag(
        order.id,
        order.state,
        order.failure_origin,
        latest_revision.revision_number if latest_revision is not None else None,
        latest_revision.id if latest_revision is not None else None,
        latest_audit_id,
    )


def _audit_events(
    order_id: UUID,
    operator: OperatorContext,
    result: ValidationResult,
    recorded_at: datetime,
) -> tuple[AuditEvent, ...]:
    if result.route is ValidationRoute.NEEDS_REVIEW:
        route_type = "ORDER_REMAINS_NEEDS_REVIEW"
        route_description = (
            "Deterministic revalidation found blocking issues; human review remains required."
        )
    elif result.approval_level is ApprovalLevel.ELEVATED:
        route_type = "ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION"
        route_description = (
            "Deterministic validation passed; elevated approval is required after human correction."
        )
    else:
        route_type = "ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION"
        route_description = (
            "Deterministic validation passed; order is ready for approval after human correction."
        )

    contracts = (
        ("REVIEW_REVISION_RECORDED", "Human review revision recorded."),
        (
            "REVIEW_REVALIDATION_COMPLETED",
            "Deterministic revalidation completed for the effective human review draft.",
        ),
        (route_type, route_description),
    )
    return tuple(
        AuditEvent(
            id=uuid4(),
            order_id=order_id,
            event_type=event_type,
            actor=operator.actor,
            occurred_at=recorded_at + timedelta(microseconds=position),
            description=description,
        )
        for position, (event_type, description) in enumerate(contracts)
    )


def _require_aware_recorded_at(recorded_at: datetime) -> None:
    if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")


def _require_closed_transaction(session: AsyncSession, stage: str) -> None:
    if session.in_transaction() is not False:
        raise AssertionError(f"{stage} must leave the database transaction closed")
