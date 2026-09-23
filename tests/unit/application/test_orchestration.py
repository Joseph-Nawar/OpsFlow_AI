"""Unit tests for the Phase 7 orchestration intake application service."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.exc import SQLAlchemyError

import opsflow.application.orchestration as orchestration_module
from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
    SourceIdentityMismatchError,
    ValidationFactsChangedError,
)
from opsflow.application.orders import (
    CreateOrderDisposition,
    CreateOrderInput,
    CreateOrderResult,
    fingerprint_order_request,
)
from opsflow.application.validation import ValidationApplicationResult
from opsflow.documents.common import normalize_mime_type, sha256_bytes
from opsflow.documents.errors import DocumentParseError
from opsflow.documents.models import CanonicalDocument, DocumentInput
from opsflow.domain import Order, OrderState, SourceDocument, SourceDocumentType
from opsflow.extraction.errors import (
    ExtractionResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.orchestration.claims import IntakeClaim, IntakeClaimKind
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.orchestration.contracts import IntakeExecution, OrchestrationIntakeCommand
from opsflow.persistence.repositories import PersistedOrder
from opsflow.review.composition import build_demo_review_runtime
from opsflow.validation import ApprovalLevel, ValidationResult, ValidationRoute

CONTENT = b"synthetic purchase-order document"
SOURCE_SHA = sha256_bytes(CONTENT)
SOURCE_ID = UUID(int=2)
ORDER_ID = UUID(int=1)
RECORDED_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
ACTOR = "orchestration:n8n"
COMMAND = OrchestrationIntakeCommand(
    content=CONTENT,
    document_type=SourceDocumentType.PDF,
    filename=r"/incoming\nested/purchase-order.pdf",
    mime_type=" Application/PDF; charset=UTF-8 ",
    message_id="message-1",
    idempotency_key="key-1",
)


class _Transaction:
    def __init__(self, session: "_Session") -> None:
        self.session = session

    async def __aenter__(self) -> "_Session":
        assert not self.session.in_transaction()
        self.session._transaction_open = True
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.session._transaction_open = False


class _Session:
    def __init__(self) -> None:
        self._transaction_open = False

    def begin(self) -> _Transaction:
        return _Transaction(self)

    def in_transaction(self) -> bool:
        return self._transaction_open


class _Provider:
    pass


def _source() -> SourceDocument:
    return SourceDocument(
        id=SOURCE_ID,
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256=SOURCE_SHA,
        message_id="message-1",
        storage_reference=None,
        metadata=(),
    )


def _order(state: OrderState) -> Order:
    order = Order.received(ORDER_ID, source_documents=(_source(),))
    if state is OrderState.PROCESSING:
        return order.transition_to(OrderState.PROCESSING)
    return replace(order, state=state)


def _persisted(state: OrderState) -> PersistedOrder:
    return PersistedOrder(order=_order(state), created_at=RECORDED_AT, validation_issues=())


def _canonical() -> CanonicalDocument:
    return CanonicalDocument(
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256=SOURCE_SHA,
        size_bytes=len(CONTENT),
        source_reference=None,
        metadata=(),
        text="synthetic source",
        pages=(),
        tables=(),
        warnings=(),
    )


def _draft(*, source_sha256: str = SOURCE_SHA) -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256=source_sha256,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme Industries",
        customer_reference="CUST-001",
        po_number="PO-001",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 1, 8),
        currency="USD",
        lines=(
            ExtractedLine(
                sku="SKU-001",
                description="Widget",
                quantity=Decimal("1"),
                submitted_price=Decimal("10"),
            ),
        ),
        notes=None,
        evidence=(),
    )


def _runtime(factory: object | None = None) -> OrchestrationRuntime:
    review = build_demo_review_runtime()
    selected_factory = (lambda: _Provider()) if factory is None else factory
    return OrchestrationRuntime(
        extraction_provider_factory=selected_factory,  # type: ignore[arg-type]
        business_data_provider=review.provider,
        policy=review.policy,
        date_provider=review.date_provider,
    )


def _validation_result(route: ValidationRoute) -> ValidationResult:
    return ValidationResult(
        issues=(),
        route=route,
        approval_level=ApprovalLevel.STANDARD,
        order_total=Decimal("10"),
        validated_order_data=None,
    )


def _install_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    claim_kind: IntakeClaimKind,
    claim_state: OrderState,
    disposition: CreateOrderDisposition = CreateOrderDisposition.CREATED_BY_THIS_COMMAND,
    process_error: BaseException | None = None,
    extract_error: BaseException | None = None,
    validation_error: BaseException | None = None,
    draft: ExtractionDraft | None = None,
    validation_route: ValidationRoute = ValidationRoute.READY_FOR_APPROVAL,
) -> tuple[_Session, dict[str, object], OrchestrationRuntime]:
    session = _Session()
    calls: dict[str, object] = {
        "order": [],
        "claim": [],
        "process": [],
        "provider": [],
        "sequence": [],
    }
    created = _persisted(OrderState.RECEIVED)
    claimed = _persisted(claim_state)
    extracted = replace(claimed.order, state=OrderState.EXTRACTED)
    final_state = (
        OrderState.NEEDS_REVIEW
        if validation_route is ValidationRoute.NEEDS_REVIEW
        else OrderState.READY_FOR_APPROVAL
    )

    async def create_order_with_disposition(
        received_session: _Session,
        request: CreateOrderInput,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> CreateOrderResult:
        calls["sequence"].append("create")  # type: ignore[attr-defined]
        calls["order"].append((received_session, request, idempotency_key, now))  # type: ignore[attr-defined]
        return CreateOrderResult(created, disposition)

    async def claim_intake_execution(
        received_session: _Session,
        **kwargs: object,
    ) -> IntakeClaim:
        calls["sequence"].append("claim")  # type: ignore[attr-defined]
        calls["claim"].append((received_session, kwargs))  # type: ignore[attr-defined]
        return IntakeClaim(claim_kind, claimed, SOURCE_ID)

    def process_document(document: DocumentInput) -> CanonicalDocument:
        calls["sequence"].append("process")  # type: ignore[attr-defined]
        calls["process"].append(document)  # type: ignore[attr-defined]
        if process_error is not None:
            raise process_error
        return _canonical()

    provider = _Provider()

    def extraction_provider_factory() -> _Provider:
        assert not session.in_transaction()
        calls["sequence"].append("provider")  # type: ignore[attr-defined]
        calls["provider"].append(provider)  # type: ignore[attr-defined]
        return provider

    class Extractor:
        def __init__(self, received_provider: _Provider) -> None:
            calls["sequence"].append("extract")  # type: ignore[attr-defined]
            calls["extractor_provider"] = received_provider

        async def extract(self, canonical: CanonicalDocument) -> ExtractionDraft:
            assert not session.in_transaction()
            calls["canonical"] = canonical
            if extract_error is not None:
                raise extract_error
            return _draft() if draft is None else draft

    async def persist_extraction_completed(
        received_session: _Session,
        *,
        order_id: UUID,
        actor: str,
        recorded_at: datetime,
    ) -> PersistedOrder:
        assert not received_session.in_transaction()
        calls["sequence"].append("extraction_completed")  # type: ignore[attr-defined]
        calls["extraction_completed"] = (order_id, actor, recorded_at)
        return PersistedOrder(extracted, RECORDED_AT, ())

    async def validate_order(
        received_session: _Session,
        order_id: UUID,
        source_document_id: UUID,
        received_draft: ExtractionDraft,
        provider: object,
        policy: object,
        context: object,
        recorded_at: datetime,
    ) -> ValidationApplicationResult:
        assert not received_session.in_transaction()
        calls["sequence"].append("validate")  # type: ignore[attr-defined]
        calls["validate"] = (
            order_id,
            source_document_id,
            received_draft,
            provider,
            policy,
            context,
            recorded_at,
        )
        if validation_error is not None:
            raise validation_error
        result = _validation_result(validation_route)
        return ValidationApplicationResult(
            order=replace(extracted, state=final_state),
            validation_result=result,
            snapshot_id=UUID(int=3),
        )

    async def persist_failure(
        received_session: _Session,
        *,
        order_id: UUID,
        classification: object,
        actor: str,
        recorded_at: datetime,
    ) -> PersistedOrder:
        assert not received_session.in_transaction()
        calls["sequence"].append("failure")  # type: ignore[attr-defined]
        calls["failure"] = (order_id, classification, actor, recorded_at)
        target = classification.target  # type: ignore[attr-defined]
        origin = classification.origin  # type: ignore[attr-defined]
        base = claimed.order
        if base.state is not origin:
            base = replace(base, state=origin, failure_origin=None)
        return PersistedOrder(
            order=base.transition_to(target),
            created_at=RECORDED_AT,
            validation_issues=(),
        )

    monkeypatch.setattr(
        orchestration_module,
        "create_order_with_disposition",
        create_order_with_disposition,
    )
    monkeypatch.setattr(orchestration_module, "claim_intake_execution", claim_intake_execution)
    monkeypatch.setattr(orchestration_module, "process_document", process_document)
    monkeypatch.setattr(orchestration_module, "OrderExtractor", Extractor)
    monkeypatch.setattr(
        orchestration_module,
        "_persist_extraction_completed",
        persist_extraction_completed,
    )
    monkeypatch.setattr(orchestration_module, "validate_order", validate_order)
    monkeypatch.setattr(orchestration_module, "persist_orchestration_failure", persist_failure)
    return session, calls, _runtime(extraction_provider_factory)


def test_server_owned_composition_and_initial_success_call_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, calls, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.INITIAL,
        claim_state=OrderState.PROCESSING,
    )
    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    assert result.state is OrderState.READY_FOR_APPROVAL
    assert result.failure_origin is None
    assert result.idempotent_replay is False
    assert result.execution is IntakeExecution.COMPLETED
    assert calls["sequence"] == [
        "create",
        "claim",
        "process",
        "provider",
        "extract",
        "extraction_completed",
        "validate",
    ]

    create_call = calls["order"][0]  # type: ignore[index]
    create_input = create_call[1]
    source_input = create_input.source_documents[0]
    assert create_input.customer_reference is None
    assert create_input.po_number is None
    assert create_input.order_date is None
    assert create_input.requested_delivery_date is None
    assert create_input.currency is None
    assert create_input.lines == ()
    assert source_input.name == "purchase-order.pdf"
    assert source_input.mime_type == normalize_mime_type(COMMAND.mime_type)
    assert source_input.sha256 == SOURCE_SHA
    assert source_input.message_id == COMMAND.message_id
    assert source_input.storage_reference is None
    assert source_input.metadata == ()
    assert create_call[2] == COMMAND.idempotency_key
    assert create_call[3] == RECORDED_AT

    claim_call = calls["claim"][0]  # type: ignore[index]
    assert claim_call[1]["request_fingerprint"] == fingerprint_order_request(create_input)
    assert claim_call[1]["recorded_at"] == RECORDED_AT + timedelta(microseconds=1)
    document = calls["process"][0]  # type: ignore[index]
    assert document == DocumentInput(
        document_type=COMMAND.document_type,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        content=CONTENT,
        source_reference=None,
        metadata=(),
    )
    assert calls["provider"] == [calls["extractor_provider"]]
    assert calls["extraction_completed"][2] == RECORDED_AT + timedelta(microseconds=2)  # type: ignore[index]
    assert calls["validate"][6] == RECORDED_AT + timedelta(microseconds=3)  # type: ignore[index]
    assert not session.in_transaction()


def test_replayed_creation_disposition_sets_idempotent_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.RESUME_PROCESSING,
        claim_state=OrderState.PROCESSING,
        disposition=CreateOrderDisposition.REPLAYED_EXISTING,
    )

    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    assert result.idempotent_replay is True


@pytest.mark.parametrize(
    ("state", "disposition"),
    [
        (OrderState.PROCESSING, CreateOrderDisposition.REPLAYED_EXISTING),
        (OrderState.EXTRACTED, CreateOrderDisposition.REPLAYED_EXISTING),
        (OrderState.NEEDS_REVIEW, CreateOrderDisposition.REPLAYED_EXISTING),
        (OrderState.READY_FOR_APPROVAL, CreateOrderDisposition.CREATED_BY_THIS_COMMAND),
    ],
)
def test_stand_down_never_runs_pipeline_or_provider(
    monkeypatch: pytest.MonkeyPatch,
    state: OrderState,
    disposition: CreateOrderDisposition,
) -> None:
    session, calls, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.STAND_DOWN,
        claim_state=state,
        disposition=disposition,
    )

    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    assert result.execution is IntakeExecution.STANDING_DOWN
    assert result.state is state
    assert result.idempotent_replay is (disposition is CreateOrderDisposition.REPLAYED_EXISTING)
    assert calls["sequence"] == ["create", "claim"]
    assert calls["process"] == []
    assert calls["provider"] == []
    assert "extractor_provider" not in calls
    assert "extraction_completed" not in calls
    assert "validate" not in calls
    assert "failure" not in calls


@pytest.mark.parametrize(
    ("error", "target"),
    [
        (ProviderTimeoutError("timeout"), OrderState.FAILED_RETRYABLE),
        (ProviderUnavailableError("unavailable"), OrderState.FAILED_RETRYABLE),
        (ExtractionResponseError("invalid response"), OrderState.FAILED_FINAL),
        (DocumentParseError("invalid document"), OrderState.FAILED_FINAL),
    ],
)
def test_processing_position_failures_persist_at_extraction_stage(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    target: OrderState,
) -> None:
    is_document_failure = isinstance(error, DocumentParseError)
    session, calls, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.INITIAL,
        claim_state=OrderState.PROCESSING,
        process_error=error if is_document_failure else None,
        extract_error=None if is_document_failure else error,
    )

    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    assert result.state is target
    assert result.failure_origin is OrderState.PROCESSING
    assert result.execution is IntakeExecution.COMPLETED
    assert calls["failure"][3] == RECORDED_AT + timedelta(microseconds=2)  # type: ignore[index]
    assert "extraction_completed" not in calls
    assert "validate" not in calls


def test_resumed_extracted_reconstruction_validates_without_lifecycle_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, calls, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.RESUME_EXTRACTED,
        claim_state=OrderState.EXTRACTED,
    )

    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    assert result.state is OrderState.READY_FOR_APPROVAL
    assert calls["canonical"].sha256 == SOURCE_SHA  # type: ignore[index]
    assert "extraction_completed" not in calls
    assert calls["validate"][1] == SOURCE_ID  # type: ignore[index]
    assert calls["validate"][6] == RECORDED_AT + timedelta(microseconds=3)  # type: ignore[index]


@pytest.mark.parametrize(
    ("error", "target"),
    [
        (ProviderTimeoutError("timeout"), OrderState.FAILED_RETRYABLE),
        (ProviderUnavailableError("unavailable"), OrderState.FAILED_RETRYABLE),
        (ExtractionResponseError("invalid response"), OrderState.FAILED_FINAL),
        (DocumentParseError("invalid document"), OrderState.FAILED_FINAL),
    ],
)
def test_resumed_extracted_reconstruction_failures_use_extracted_position(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    target: OrderState,
) -> None:
    session, calls, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.RESUME_EXTRACTED,
        claim_state=OrderState.EXTRACTED,
        extract_error=error,
    )

    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    assert result.state is target
    assert result.failure_origin is OrderState.EXTRACTED
    assert calls["failure"][3] == RECORDED_AT + timedelta(microseconds=2)  # type: ignore[index]
    assert "validate" not in calls


def test_reconstructed_draft_identity_mismatch_is_not_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, calls, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.RESUME_EXTRACTED,
        claim_state=OrderState.EXTRACTED,
        draft=_draft(source_sha256="b" * 64),
    )

    with pytest.raises(SourceIdentityMismatchError):
        asyncio.run(
            orchestration_module.execute_orchestration_intake(
                session, COMMAND, runtime, ACTOR, RECORDED_AT
            )
        )

    assert "failure" not in calls
    assert "validate" not in calls


@pytest.mark.parametrize(
    "error",
    [BusinessDataProviderError(), ValidationFactsChangedError(ORDER_ID), InvalidTrustedDataError()],
)
def test_validation_operational_failures_persist_at_validation_stage(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    session, calls, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.RESUME_EXTRACTED,
        claim_state=OrderState.EXTRACTED,
        validation_error=error,
    )

    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    assert result.state in {OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL}
    assert result.failure_origin is OrderState.EXTRACTED
    assert calls["failure"][3] == RECORDED_AT + timedelta(microseconds=3)  # type: ignore[index]


@pytest.mark.parametrize(
    "route", [ValidationRoute.NEEDS_REVIEW, ValidationRoute.READY_FOR_APPROVAL]
)
def test_business_validation_routes_are_successful_completed_results(
    monkeypatch: pytest.MonkeyPatch,
    route: ValidationRoute,
) -> None:
    session, _, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.INITIAL,
        claim_state=OrderState.PROCESSING,
        validation_route=route,
    )

    result = asyncio.run(
        orchestration_module.execute_orchestration_intake(
            session, COMMAND, runtime, ACTOR, RECORDED_AT
        )
    )

    expected_state = (
        OrderState.NEEDS_REVIEW
        if route is ValidationRoute.NEEDS_REVIEW
        else OrderState.READY_FOR_APPROVAL
    )
    assert result.state is expected_state
    assert result.failure_origin is None
    assert result.execution is IntakeExecution.COMPLETED


@pytest.mark.parametrize("boundary", ["create", "claim", "transition", "validate", "failure"])
def test_sqlalchemy_failures_become_safe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    session, _, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.INITIAL,
        claim_state=OrderState.PROCESSING,
        validation_error=BusinessDataProviderError() if boundary == "failure" else None,
    )
    diagnostic = "SQL-DIAGNOSTIC-DO-NOT-LEAK"

    if boundary == "create":

        async def fail_create(*args: object, **kwargs: object) -> CreateOrderResult:
            del args, kwargs
            raise SQLAlchemyError(diagnostic)

        monkeypatch.setattr(orchestration_module, "create_order_with_disposition", fail_create)
    elif boundary == "claim":

        async def fail_claim(*args: object, **kwargs: object) -> IntakeClaim:
            del args, kwargs
            raise SQLAlchemyError(diagnostic)

        monkeypatch.setattr(orchestration_module, "claim_intake_execution", fail_claim)
    elif boundary == "transition":

        async def fail_transition(*args: object, **kwargs: object) -> PersistedOrder:
            del args, kwargs
            raise SQLAlchemyError(diagnostic)

        monkeypatch.setattr(orchestration_module, "_persist_extraction_completed", fail_transition)
    elif boundary == "validate":

        async def fail_validate(*args: object, **kwargs: object) -> ValidationApplicationResult:
            del args, kwargs
            raise SQLAlchemyError(diagnostic)

        monkeypatch.setattr(orchestration_module, "validate_order", fail_validate)
    else:

        async def fail_failure(*args: object, **kwargs: object) -> PersistedOrder:
            del args, kwargs
            raise SQLAlchemyError(diagnostic)

        monkeypatch.setattr(orchestration_module, "persist_orchestration_failure", fail_failure)

    with pytest.raises(orchestration_module.OrchestrationUnavailableError) as raised:
        asyncio.run(
            orchestration_module.execute_orchestration_intake(
                session, COMMAND, runtime, ACTOR, RECORDED_AT
            )
        )

    assert str(raised.value) == "Orchestration intake is currently unavailable."
    assert diagnostic not in str(raised.value)
    assert diagnostic not in repr(raised.value)


@pytest.mark.parametrize("stage", ["process", "provider", "extract", "validate"])
def test_unexpected_runtime_errors_surface_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    unexpected = RuntimeError("unexpected-programming-defect")
    process_error = unexpected if stage == "process" else None
    extract_error = unexpected if stage == "extract" else None
    validation_error = unexpected if stage == "validate" else None
    session, _, runtime = _install_pipeline(
        monkeypatch,
        claim_kind=IntakeClaimKind.INITIAL,
        claim_state=OrderState.PROCESSING,
        process_error=process_error,
        extract_error=extract_error,
        validation_error=validation_error,
    )
    if stage == "provider":

        def unexpected_provider() -> _Provider:
            raise unexpected

        runtime = _runtime(unexpected_provider)

    with pytest.raises(RuntimeError, match="unexpected-programming-defect"):
        asyncio.run(
            orchestration_module.execute_orchestration_intake(
                session, COMMAND, runtime, ACTOR, RECORDED_AT
            )
        )


def test_processing_to_extracted_helper_uses_one_short_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    persisted = _persisted(OrderState.PROCESSING)
    updates: list[Order] = []
    audits: list[object] = []

    async def get_for_update(received_session: _Session, order_id: UUID) -> PersistedOrder:
        assert received_session is session
        assert order_id == ORDER_ID
        return persisted

    async def update_order(received_session: _Session, order: Order) -> None:
        assert received_session.in_transaction()
        updates.append(order)

    async def insert_audit(received_session: _Session, event: object) -> None:
        assert received_session.in_transaction()
        audits.append(event)

    monkeypatch.setattr(orchestration_module, "get_order_for_update", get_for_update)
    monkeypatch.setattr(orchestration_module, "update_order_snapshot", update_order)
    monkeypatch.setattr(orchestration_module, "insert_audit_event", insert_audit)

    result = asyncio.run(
        orchestration_module._persist_extraction_completed(
            session,
            order_id=ORDER_ID,
            actor=ACTOR,
            recorded_at=RECORDED_AT,
        )
    )

    assert result.order.state is OrderState.EXTRACTED
    assert updates[0].state is OrderState.EXTRACTED
    assert audits[0].event_type == "ORDER_EXTRACTION_COMPLETED"
    assert audits[0].occurred_at == RECORDED_AT
    assert audits[0].description == (
        "Document processing and structured extraction completed; validation is pending."
    )
    assert not session.in_transaction()
