"""Application service for one Phase 7 orchestration intake execution."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
    OrderNotFoundError,
    OrderValidationStateError,
    SourceIdentityMismatchError,
    ValidationFactsChangedError,
)
from opsflow.application.orders import (
    CreateOrderDisposition,
    CreateOrderInput,
    CreateSourceDocumentInput,
    create_order_with_disposition,
    fingerprint_order_request,
)
from opsflow.application.validation import validate_order
from opsflow.documents.common import normalize_mime_type, sha256_bytes
from opsflow.documents.errors import DocumentProcessingError
from opsflow.documents.models import DocumentInput
from opsflow.documents.processor import process_document
from opsflow.domain import AuditEvent, Order, OrderState
from opsflow.extraction.errors import ExtractionResponseError, ProviderError
from opsflow.extraction.extractor import OrderExtractor
from opsflow.orchestration.claims import (
    IntakeClaim,
    IntakeClaimKind,
    OrchestrationSourceIdentity,
    claim_intake_execution,
)
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.orchestration.contracts import (
    IntakeExecution,
    OrchestrationIntakeCommand,
    OrchestrationIntakeResult,
)
from opsflow.orchestration.failures import (
    FailureClassification,
    classify_extracted_failure,
    classify_processing_failure,
    persist_orchestration_failure,
)
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_order_for_update,
    insert_audit_event,
    update_order_snapshot,
)
from opsflow.validation import ValidationContext

_UNAVAILABLE_MESSAGE = "Orchestration intake is currently unavailable."
_EXTRACTION_COMPLETED_DESCRIPTION = (
    "Document processing and structured extraction completed; validation is pending."
)


class OrchestrationUnavailableError(Exception):
    """The orchestration application could not prove a durable result."""

    def __init__(self) -> None:
        super().__init__(_UNAVAILABLE_MESSAGE)


def _basename(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def _require_aware_recorded_at(recorded_at: datetime) -> None:
    if not isinstance(recorded_at, datetime) or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")


def _completed_result(
    persisted: PersistedOrder,
    *,
    idempotent_replay: bool,
) -> OrchestrationIntakeResult:
    return OrchestrationIntakeResult(
        order_id=persisted.order.id,
        state=persisted.order.state,
        failure_origin=persisted.order.failure_origin,
        idempotent_replay=idempotent_replay,
        execution=IntakeExecution.COMPLETED,
    )


def _completed_order_result(
    order: Order,
    *,
    idempotent_replay: bool,
) -> OrchestrationIntakeResult:
    return OrchestrationIntakeResult(
        order_id=order.id,
        state=order.state,
        failure_origin=order.failure_origin,
        idempotent_replay=idempotent_replay,
        execution=IntakeExecution.COMPLETED,
    )


def _standing_down_result(
    claim: IntakeClaim,
    *,
    idempotent_replay: bool,
) -> OrchestrationIntakeResult:
    return OrchestrationIntakeResult(
        order_id=claim.persisted.order.id,
        state=claim.persisted.order.state,
        failure_origin=claim.persisted.order.failure_origin,
        idempotent_replay=idempotent_replay,
        execution=IntakeExecution.STANDING_DOWN,
    )


async def _persist_failure_result(
    session: AsyncSession,
    *,
    order_id: UUID,
    error: BaseException,
    classifier: Callable[[BaseException], FailureClassification],
    actor: str,
    recorded_at: datetime,
    review_base_url: str,
    idempotent_replay: bool,
) -> OrchestrationIntakeResult:
    classification = classifier(error)
    try:
        persisted = await persist_orchestration_failure(
            session,
            order_id=order_id,
            classification=classification,
            actor=actor,
            recorded_at=recorded_at,
            review_base_url=review_base_url,
        )
    except SQLAlchemyError:
        raise OrchestrationUnavailableError() from None
    return _completed_result(persisted, idempotent_replay=idempotent_replay)


async def _persist_extraction_completed(
    session: AsyncSession,
    *,
    order_id: UUID,
    actor: str,
    recorded_at: datetime,
) -> PersistedOrder:
    _require_aware_recorded_at(recorded_at)
    async with session.begin():
        locked = await get_order_for_update(session, order_id)
        if locked is None:
            raise OrderNotFoundError(order_id)
        if locked.order.state is not OrderState.PROCESSING:
            raise OrderValidationStateError(order_id, locked.order.state)

        extracted = locked.order.transition_to(OrderState.EXTRACTED)
        await update_order_snapshot(session, extracted)
        await insert_audit_event(
            session,
            AuditEvent(
                id=uuid4(),
                order_id=order_id,
                event_type="ORDER_EXTRACTION_COMPLETED",
                actor=actor,
                occurred_at=recorded_at,
                description=_EXTRACTION_COMPLETED_DESCRIPTION,
            ),
        )
        persisted = PersistedOrder(
            order=extracted,
            created_at=locked.created_at,
            validation_issues=locked.validation_issues,
        )
    return persisted


async def execute_orchestration_intake(
    session: AsyncSession,
    command: OrchestrationIntakeCommand,
    runtime: OrchestrationRuntime,
    actor: str,
    recorded_at: datetime,
) -> OrchestrationIntakeResult:
    """Execute one claimed document through Phases 2–5."""

    _require_aware_recorded_at(recorded_at)
    basename = _basename(command.filename)
    normalized_mime_type = normalize_mime_type(command.mime_type)
    source_sha256 = sha256_bytes(command.content)
    source_input = CreateSourceDocumentInput(
        document_type=command.document_type,
        name=basename,
        mime_type=normalized_mime_type,
        sha256=source_sha256,
        message_id=command.message_id,
        storage_reference=None,
        metadata=(("source_system", "GMAIL"),) if command.source_system == "GMAIL" else (),
    )
    create_input = CreateOrderInput(
        customer_reference=None,
        po_number=None,
        order_date=None,
        requested_delivery_date=None,
        currency=None,
        lines=(),
        source_documents=(source_input,),
    )
    request_fingerprint = fingerprint_order_request(create_input)
    document_input = DocumentInput(
        document_type=command.document_type,
        name=basename,
        mime_type=normalized_mime_type,
        content=command.content,
        source_reference=None,
        metadata=(),
    )
    source_identity = OrchestrationSourceIdentity(
        document_type=command.document_type,
        name=basename,
        mime_type=normalized_mime_type,
        sha256=source_sha256,
        message_id=command.message_id,
    )

    try:
        creation = await create_order_with_disposition(
            session,
            create_input,
            command.idempotency_key,
            now=recorded_at,
        )
    except SQLAlchemyError:
        raise OrchestrationUnavailableError() from None

    idempotent_replay = creation.disposition is CreateOrderDisposition.REPLAYED_EXISTING
    try:
        claim = await claim_intake_execution(
            session,
            order_id=creation.persisted.order.id,
            idempotency_key=command.idempotency_key,
            request_fingerprint=request_fingerprint,
            source=source_identity,
            actor=actor,
            recorded_at=recorded_at + timedelta(microseconds=1),
        )
    except SQLAlchemyError:
        raise OrchestrationUnavailableError() from None

    if claim.kind is IntakeClaimKind.STAND_DOWN:
        return _standing_down_result(claim, idempotent_replay=idempotent_replay)

    processing_classifier = (
        classify_processing_failure
        if claim.kind in (IntakeClaimKind.INITIAL, IntakeClaimKind.RESUME_PROCESSING)
        else classify_extracted_failure
    )
    failure_at = recorded_at + timedelta(microseconds=2)
    try:
        canonical = process_document(document_input)
    except (DocumentProcessingError, ProviderError, ExtractionResponseError) as error:
        return await _persist_failure_result(
            session,
            order_id=claim.persisted.order.id,
            error=error,
            classifier=processing_classifier,
            actor=actor,
            recorded_at=failure_at,
            review_base_url=runtime.review_base_url,
            idempotent_replay=idempotent_replay,
        )

    if session.in_transaction():
        raise RuntimeError("orchestration provider call requires no active transaction")
    try:
        provider = runtime.extraction_provider_factory()
        draft = await OrderExtractor(provider).extract(canonical)
    except (DocumentProcessingError, ProviderError, ExtractionResponseError) as error:
        return await _persist_failure_result(
            session,
            order_id=claim.persisted.order.id,
            error=error,
            classifier=processing_classifier,
            actor=actor,
            recorded_at=failure_at,
            review_base_url=runtime.review_base_url,
            idempotent_replay=idempotent_replay,
        )

    if (
        draft.source_sha256 != source_identity.sha256
        or draft.source_document_type is not source_identity.document_type
    ):
        raise SourceIdentityMismatchError(
            claim.persisted.order.id,
            claim.source_document_id,
        )

    if claim.kind in (IntakeClaimKind.INITIAL, IntakeClaimKind.RESUME_PROCESSING):
        try:
            await _persist_extraction_completed(
                session,
                order_id=claim.persisted.order.id,
                actor=actor,
                recorded_at=failure_at,
            )
        except SQLAlchemyError:
            raise OrchestrationUnavailableError() from None

    try:
        validation = await validate_order(
            session,
            claim.persisted.order.id,
            claim.source_document_id,
            draft,
            runtime.business_data_provider,
            runtime.policy,
            ValidationContext(evaluation_date=runtime.date_provider.current_date()),
            recorded_at + timedelta(microseconds=3),
            runtime.review_base_url,
        )
    except (
        BusinessDataProviderError,
        InvalidTrustedDataError,
        ValidationFactsChangedError,
    ) as error:
        return await _persist_failure_result(
            session,
            order_id=claim.persisted.order.id,
            error=error,
            classifier=classify_extracted_failure,
            actor=actor,
            recorded_at=recorded_at + timedelta(microseconds=3),
            review_base_url=runtime.review_base_url,
            idempotent_replay=idempotent_replay,
        )
    except SQLAlchemyError:
        raise OrchestrationUnavailableError() from None

    return _completed_order_result(validation.order, idempotent_replay=idempotent_replay)


__all__ = ["OrchestrationUnavailableError", "execute_orchestration_intake"]
