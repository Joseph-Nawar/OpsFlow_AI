"""Internal Phase 5 validation orchestration."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import AuditEvent, Order, OrderState, SourceDocument
from opsflow.extraction.models import ExtractionDraft
from opsflow.persistence.mappers import (
    PersistedExtractionSnapshot,
    extraction_draft_to_payload,
)
from opsflow.persistence.repositories import (
    PersistedOrder,
    build_validation_facts,
    get_extraction_snapshot,
    get_order,
    get_order_for_update,
    get_source_document_order_id,
    insert_audit_event,
    insert_extraction_snapshot,
    replace_order_graph,
    replace_validation_issues,
    update_order_snapshot,
)
from opsflow.validation import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
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

from .errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
    OrderNotFoundError,
    OrderValidationStateError,
    SnapshotConflictError,
    SnapshotReplayError,
    SourceDocumentNotFoundError,
    SourceIdentityMismatchError,
    SourceOwnershipError,
    ValidationFactsChangedError,
)


@dataclass(frozen=True, slots=True)
class ValidationApplicationResult:
    """Committed result of one internal validation operation."""

    order: Order
    validation_result: ValidationResult
    snapshot_id: UUID


async def validate_order(
    session: AsyncSession,
    order_id: UUID,
    source_document_id: UUID,
    draft: ExtractionDraft,
    business_data_provider: BusinessDataProvider,
    policy: ValidationPolicy,
    context: ValidationContext,
    recorded_at: datetime,
) -> ValidationApplicationResult:
    """Validate and atomically route one already-extracted order."""

    _require_aware_recorded_at(recorded_at)

    try:
        persisted = await get_order(session, order_id)
        if persisted is None:
            raise OrderNotFoundError(order_id)
        source_document = await _require_owned_source(
            session, persisted, order_id, source_document_id
        )
        _require_source_identity(order_id, source_document_id, source_document, draft)
        _require_extracted_state(persisted, order_id)
        existing_snapshot = await get_extraction_snapshot(session, order_id, source_document_id)
        _raise_snapshot_status(existing_snapshot, draft, order_id, source_document_id)
    except Exception:
        await session.rollback()
        raise
    await session.rollback()

    trusted_business_data = await _get_trusted_business_data(business_data_provider, draft)
    try:
        canonical_customer_reference = _canonical_customer_reference(trusted_business_data)
        validation_facts = await build_validation_facts(
            session,
            order_id=order_id,
            source_document_id=source_document_id,
            canonical_customer_reference=canonical_customer_reference,
            po_number=draft.po_number,
            source_sha256=draft.source_sha256,
        )
    except Exception:
        await session.rollback()
        raise
    await session.rollback()

    validation_result = validation_engine.validate(
        draft,
        trusted_business_data,
        validation_facts,
        policy,
        context,
    )
    snapshot_id = uuid4()

    async with session.begin():
        locked = await get_order_for_update(session, order_id)
        if locked is None:
            raise OrderNotFoundError(order_id)
        source_document = await _require_owned_source(session, locked, order_id, source_document_id)
        _require_source_identity(order_id, source_document_id, source_document, draft)
        _require_extracted_state(locked, order_id)
        existing_snapshot = await get_extraction_snapshot(session, order_id, source_document_id)
        _raise_snapshot_status(existing_snapshot, draft, order_id, source_document_id)

        fresh_facts = await build_validation_facts(
            session,
            order_id=order_id,
            source_document_id=source_document_id,
            canonical_customer_reference=canonical_customer_reference,
            po_number=draft.po_number,
            source_sha256=draft.source_sha256,
        )
        if fresh_facts != validation_facts:
            raise ValidationFactsChangedError(order_id)

        await insert_extraction_snapshot(
            session,
            PersistedExtractionSnapshot(
                id=snapshot_id,
                order_id=order_id,
                source_document_id=source_document_id,
                source_sha256=draft.source_sha256,
                source_document_type=draft.source_document_type,
                draft=draft,
                created_at=recorded_at,
            ),
        )
        await replace_validation_issues(session, order_id, validation_result.issues)

        if validation_result.route is ValidationRoute.READY_FOR_APPROVAL:
            if validation_result.validated_order_data is None:
                raise InvalidTrustedDataError()
            line_ids = tuple(uuid4() for _ in validation_result.validated_order_data.lines)
            promoted = locked.order.promote_validated_data(
                validation_result.validated_order_data,
                line_ids,
            )
            final_order = promoted.transition_to(OrderState.VALIDATED).transition_to(
                OrderState.READY_FOR_APPROVAL
            )
        else:
            final_order = locked.order.transition_to(OrderState.VALIDATED).transition_to(
                OrderState.NEEDS_REVIEW
            )

        await update_order_snapshot(session, final_order)
        if validation_result.route is ValidationRoute.READY_FOR_APPROVAL:
            await replace_order_graph(session, final_order)

        descriptions = (
            "Immutable extraction snapshot recorded for the order source document.",
            "Deterministic validation completed.",
            _route_description(validation_result),
        )
        event_types = (
            "EXTRACTION_SNAPSHOT_RECORDED",
            "ORDER_VALIDATED",
            "ORDER_READY_FOR_APPROVAL"
            if validation_result.route is ValidationRoute.READY_FOR_APPROVAL
            else "ORDER_NEEDS_REVIEW",
        )
        for position, (event_type, description) in enumerate(
            zip(event_types, descriptions, strict=True)
        ):
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type=event_type,
                    actor="system",
                    occurred_at=recorded_at + timedelta(microseconds=position),
                    description=description,
                ),
            )

    return ValidationApplicationResult(
        order=final_order,
        validation_result=validation_result,
        snapshot_id=snapshot_id,
    )


async def _get_trusted_business_data(
    provider: BusinessDataProvider,
    draft: ExtractionDraft,
) -> TrustedBusinessData:
    request = BusinessDataLookupRequest(
        customer_reference=draft.customer_reference,
        customer_name=None if draft.customer_reference is not None else draft.customer_name,
        skus=tuple(line.sku for line in draft.lines),
    )
    try:
        data = await provider.get_validation_data(request)
        validate_trusted_business_data(draft, data)
    except TrustedBusinessDataContractError:
        raise InvalidTrustedDataError() from None
    except Exception:
        raise BusinessDataProviderError() from None
    return data


async def _require_owned_source(
    session: AsyncSession,
    persisted: PersistedOrder,
    order_id: UUID,
    source_document_id: UUID,
) -> SourceDocument:
    for source_document in persisted.order.source_documents:
        if source_document.id == source_document_id:
            return source_document

    owner_id = await get_source_document_order_id(session, source_document_id)
    if owner_id is None:
        raise SourceDocumentNotFoundError(source_document_id)
    raise SourceOwnershipError(order_id, source_document_id)


def _require_source_identity(
    order_id: UUID,
    source_document_id: UUID,
    source_document: SourceDocument,
    draft: ExtractionDraft,
) -> None:
    if (
        source_document.sha256.casefold() != draft.source_sha256
        or source_document.document_type is not draft.source_document_type
    ):
        raise SourceIdentityMismatchError(order_id, source_document_id)


def _require_extracted_state(persisted: PersistedOrder, order_id: UUID) -> None:
    if persisted.order.state is not OrderState.EXTRACTED:
        raise OrderValidationStateError(order_id, persisted.order.state)


def _raise_snapshot_status(
    existing_snapshot: PersistedExtractionSnapshot | None,
    draft: ExtractionDraft,
    order_id: UUID,
    source_document_id: UUID,
) -> None:
    if existing_snapshot is None:
        return
    if (
        existing_snapshot.source_sha256 == draft.source_sha256
        and existing_snapshot.source_document_type is draft.source_document_type
        and extraction_draft_to_payload(existing_snapshot.draft)
        == extraction_draft_to_payload(draft)
    ):
        raise SnapshotReplayError(order_id, source_document_id)
    raise SnapshotConflictError(order_id, source_document_id)


def _canonical_customer_reference(data: TrustedBusinessData) -> str | None:
    if len(data.customer_candidates) != 1:
        return None
    candidate = data.customer_candidates[0]
    if not candidate.active:
        return None
    return candidate.reference


def _route_description(result: ValidationResult) -> str:
    if result.route is ValidationRoute.READY_FOR_APPROVAL:
        if result.approval_level.value == "ELEVATED":
            return "Deterministic validation passed; elevated approval is required."
        return "Deterministic validation passed; order is ready for approval."
    return "Deterministic validation found one or more blocking issues; human review is required."


def _require_aware_recorded_at(recorded_at: datetime) -> None:
    if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
