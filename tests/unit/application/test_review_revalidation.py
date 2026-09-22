"""Unit coverage for the Phase 6 Save & revalidate orchestration boundary."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

import opsflow.application.review_revalidation as review_module
from opsflow.application.errors import (
    BusinessDataProviderError,
    ForbiddenError,
    InvalidReviewStateError,
    InvalidTrustedDataError,
    NoReviewChangesError,
    OrderNotFoundError,
    ReviewCaseUnavailableError,
    ReviewPreconditionFailedError,
    ReviewPreconditionRequiredError,
    ValidationFactsChangedError,
)
from opsflow.domain import (
    AuditEvent,
    Order,
    OrderLine,
    OrderState,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.extraction.models import Evidence, ExtractedLine, ExtractionDraft
from opsflow.persistence.mappers import PersistedExtractionSnapshot
from opsflow.persistence.repositories import PersistedOrder
from opsflow.review import (
    OperatorContext,
    OperatorRole,
    ReviewChange,
    ReviewDraft,
    ReviewLine,
    ReviewRevision,
)
from opsflow.review.concurrency import compute_review_etag
from opsflow.validation import (
    ApprovalLevel,
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
    ValidatedOrderData,
    ValidatedOrderLine,
    ValidationContext,
    ValidationFacts,
    ValidationResult,
    ValidationRoute,
)
from opsflow.validation.policy import ValidationPolicy

ORDER_ID = UUID(int=101)
SOURCE_ID = UUID(int=102)
SOURCE_SHA = "a" * 64
SNAPSHOT_ID = UUID(int=103)
LINE_ID = UUID(int=104)
AUDIT_ID = UUID(int=105)
RECORDED_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
EVALUATION_DATE = date(2030, 1, 2)
_DEFAULT_ETAG = object()
OPERATOR = OperatorContext("reviewer-test", OperatorRole.REVIEWER)
POLICY = ValidationPolicy(("USD",), Decimal("0.05"), Decimal("1000"))


class FakeSession:
    """Expose AsyncSession's transaction boundary used by the application service."""

    def __init__(self) -> None:
        self._transaction_open = False
        self.rollback_count = 0
        self.commit_count = 0
        self.write_rollback_count = 0

    def in_transaction(self) -> bool:
        return self._transaction_open

    async def rollback(self) -> None:
        self._transaction_open = False
        self.rollback_count += 1

    def begin(self) -> "FakeTransaction":
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        assert not self.session.in_transaction()
        self.session._transaction_open = True
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.session.commit_count += 1
        else:
            self.session.write_rollback_count += 1
        self.session._transaction_open = False


class FixedDateProvider:
    def __init__(self, value: date = EVALUATION_DATE) -> None:
        self.value = value
        self.calls = 0

    def current_date(self) -> date:
        self.calls += 1
        return self.value


class RecordingProvider:
    def __init__(self, session: FakeSession, result: TrustedBusinessData) -> None:
        self.session = session
        self.result = result
        self.calls: list[BusinessDataLookupRequest] = []

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        assert not self.session.in_transaction()
        self.calls.append(request)
        return self.result


def make_source() -> SourceDocument:
    return SourceDocument(
        id=SOURCE_ID,
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256=SOURCE_SHA,
        message_id="message-7",
        storage_reference="synthetic://order.pdf",
        metadata=(("mailbox", "orders-demo"),),
    )


def make_order(state: OrderState = OrderState.NEEDS_REVIEW) -> Order:
    return Order(
        id=ORDER_ID,
        customer_reference="TRUSTED-OLD",
        po_number="PO-OLD",
        order_date=date(2029, 12, 1),
        requested_delivery_date=date(2029, 12, 20),
        currency="USD",
        lines=(
            OrderLine(
                id=LINE_ID,
                sku="SKU-OLD",
                description="Previously trusted line",
                quantity=Decimal("1"),
                submitted_price=Decimal("5"),
                trusted_catalogue_price=Decimal("5"),
            ),
        ),
        source_documents=(make_source(),),
        state=state,
    )


def make_extraction_draft() -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256=SOURCE_SHA,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme Industries",
        customer_reference="CUST-001",
        po_number="PO-100",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 2, 1),
        currency="USD",
        lines=(ExtractedLine("SKU-001", "Widget", Decimal("2"), Decimal("10")),),
        notes="Keep original notes",
        evidence=(Evidence("po_number", "page 1", "PO-100"),),
    )


def make_snapshot(draft: ExtractionDraft | None = None) -> PersistedExtractionSnapshot:
    extraction = make_extraction_draft() if draft is None else draft
    return PersistedExtractionSnapshot(
        id=SNAPSHOT_ID,
        order_id=ORDER_ID,
        source_document_id=SOURCE_ID,
        source_sha256=extraction.source_sha256,
        source_document_type=extraction.source_document_type,
        draft=extraction,
        created_at=RECORDED_AT,
    )


def make_original_review_draft() -> ReviewDraft:
    return ReviewDraft(
        customer_name="Acme Industries",
        customer_reference="CUST-001",
        po_number="PO-100",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 2, 1),
        currency="USD",
        lines=(ReviewLine("SKU-001", "Widget", Decimal("2"), Decimal("10")),),
    )


def make_candidate() -> ReviewDraft:
    return replace(make_original_review_draft(), po_number="PO-101")


def make_revision(
    number: int = 1,
    *,
    payload: ReviewDraft | None = None,
    snapshot_id: UUID = SNAPSHOT_ID,
    revision_id: UUID | None = None,
) -> ReviewRevision:
    draft = make_original_review_draft() if payload is None else payload
    return ReviewRevision(
        id=revision_id or UUID(int=200 + number),
        order_id=ORDER_ID,
        extraction_snapshot_id=snapshot_id,
        revision_number=number,
        payload=draft,
        changes=(ReviewChange("po_number", "PO-99", "PO-100"),),
        actor="reviewer-prior",
        created_at=RECORDED_AT,
    )


def make_persisted_order(state: OrderState = OrderState.NEEDS_REVIEW) -> PersistedOrder:
    return PersistedOrder(make_order(state), RECORDED_AT, ())


def make_business_data() -> TrustedBusinessData:
    return TrustedBusinessData(
        customer_candidates=(TrustedCustomer("CUST-001", "Acme Industries", True),),
        products_by_line=(
            TrustedProduct("SKU-001", "Trusted Widget", True, "USD", Decimal("12"), Decimal("9")),
        ),
    )


def make_validated_data() -> ValidatedOrderData:
    return ValidatedOrderData(
        customer_reference="CUST-001",
        po_number="PO-101",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 2, 1),
        currency="USD",
        lines=(
            ValidatedOrderLine(
                sku="SKU-001",
                description="Trusted Widget",
                quantity=Decimal("2"),
                submitted_price=Decimal("10"),
                trusted_catalogue_price=Decimal("12"),
            ),
        ),
    )


def make_clean_result(*, high_value: bool = False) -> ValidationResult:
    issues = (
        (
            ValidationIssue(
                "HIGH_VALUE_APPROVAL_REQUIRED",
                ValidationSeverity.WARNING,
                "order_total",
                Decimal("1000"),
                Decimal("2000"),
                "Elevated approval is required.",
            ),
        )
        if high_value
        else ()
    )
    return ValidationResult(
        issues=issues,
        route=ValidationRoute.READY_FOR_APPROVAL,
        approval_level=ApprovalLevel.ELEVATED if high_value else ApprovalLevel.STANDARD,
        order_total=Decimal("2000" if high_value else "20"),
        validated_order_data=make_validated_data(),
    )


def make_invalid_result() -> ValidationResult:
    return ValidationResult(
        issues=(
            ValidationIssue(
                "UNKNOWN_SKU",
                ValidationSeverity.ERROR,
                "lines[0].sku",
                "known SKU",
                "SKU-UNKNOWN",
                "The SKU is not in trusted catalogue data.",
            ),
        ),
        route=ValidationRoute.NEEDS_REVIEW,
        approval_level=ApprovalLevel.STANDARD,
        order_total=None,
        validated_order_data=None,
    )


class RecordingRepositories:
    """Focused repository doubles; each read models SQLAlchemy autobegin."""

    def __init__(
        self,
        session: FakeSession,
        *,
        order: PersistedOrder | None = None,
        snapshots: tuple[PersistedExtractionSnapshot, ...] | None = None,
        latest_revision: ReviewRevision | None = None,
        audit_id: UUID | None = AUDIT_ID,
        facts: tuple[ValidationFacts, ...] = (ValidationFacts(False, False),) * 2,
    ) -> None:
        self.session = session
        self.orders = (
            [make_persisted_order(), make_persisted_order()] if order is None else [order, order]
        )
        self.snapshots = (
            [(make_snapshot(),), (make_snapshot(),)]
            if snapshots is None
            else [snapshots, snapshots]
        )
        self.latest_revisions = [latest_revision, latest_revision]
        self.audit_ids = [audit_id, audit_id]
        self.facts_values = list(facts)
        self.calls: list[tuple[str, object]] = []
        self.fact_calls: list[tuple[bool, dict[str, object]]] = []
        self.revisions: list[ReviewRevision] = []
        self.issue_sets: list[tuple[UUID, tuple[object, ...]]] = []
        self.order_updates: list[Order] = []
        self.graph_replacements: list[Order] = []
        self.audits: list[AuditEvent] = []

    def read(self) -> None:
        if not self.session.in_transaction():
            self.session._transaction_open = True

    async def get_order(self, session: FakeSession, order_id: UUID) -> PersistedOrder | None:
        self.read()
        self.calls.append(("get_order", order_id))
        return self.orders.pop(0)

    async def get_order_for_update(
        self, session: FakeSession, order_id: UUID
    ) -> PersistedOrder | None:
        self.calls.append(("get_order_for_update", order_id))
        return self.orders.pop(0)

    async def get_extraction_snapshots_for_order(
        self, session: FakeSession, order_id: UUID
    ) -> tuple[PersistedExtractionSnapshot, ...]:
        self.read()
        self.calls.append(("snapshots", order_id))
        return self.snapshots.pop(0)

    async def get_latest_review_revision(
        self, session: FakeSession, order_id: UUID
    ) -> ReviewRevision | None:
        self.read()
        self.calls.append(("latest_revision", order_id))
        return self.latest_revisions.pop(0)

    async def get_latest_audit_event_id(self, session: FakeSession, order_id: UUID) -> UUID | None:
        self.read()
        self.calls.append(("latest_audit", order_id))
        return self.audit_ids.pop(0)

    async def get_source_document_order_id(
        self, session: FakeSession, source_document_id: UUID
    ) -> UUID | None:
        self.calls.append(("source_owner", source_document_id))
        return ORDER_ID

    async def build_validation_facts(
        self, session: FakeSession, **kwargs: object
    ) -> ValidationFacts:
        was_open = session.in_transaction()
        self.fact_calls.append((was_open, kwargs))
        if not was_open:
            session._transaction_open = True
        self.calls.append(("facts", kwargs))
        return self.facts_values.pop(0)

    async def insert_review_revision(self, session: FakeSession, revision: ReviewRevision) -> None:
        assert session.in_transaction()
        self.revisions.append(revision)

    async def replace_validation_issues(
        self, session: FakeSession, order_id: UUID, issues: tuple[object, ...]
    ) -> None:
        assert session.in_transaction()
        self.issue_sets.append((order_id, issues))

    async def update_order_snapshot(self, session: FakeSession, order: Order) -> None:
        assert session.in_transaction()
        self.order_updates.append(order)

    async def replace_order_graph(self, session: FakeSession, order: Order) -> None:
        assert session.in_transaction()
        self.graph_replacements.append(order)

    async def insert_audit_event(self, session: FakeSession, event: AuditEvent) -> None:
        assert session.in_transaction()
        self.audits.append(event)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "get_order",
            "get_order_for_update",
            "get_extraction_snapshots_for_order",
            "get_latest_review_revision",
            "get_latest_audit_event_id",
            "build_validation_facts",
            "insert_review_revision",
            "replace_validation_issues",
            "update_order_snapshot",
            "replace_order_graph",
            "insert_audit_event",
        ):
            monkeypatch.setattr(review_module, name, getattr(self, name))


def current_etag(
    revision: ReviewRevision | None = None,
    *,
    order: Order | None = None,
    audit_id: UUID | None = AUDIT_ID,
) -> str:
    persisted_order = make_order() if order is None else order
    return compute_review_etag(
        ORDER_ID,
        persisted_order.state,
        persisted_order.failure_origin,
        revision.revision_number if revision is not None else None,
        revision.id if revision is not None else None,
        audit_id,
    )


def call_service(
    session: FakeSession,
    candidate: ReviewDraft | None = None,
    *,
    etag: object = _DEFAULT_ETAG,
    operator: OperatorContext = OPERATOR,
    provider: RecordingProvider | None = None,
    date_provider: FixedDateProvider | None = None,
) -> object:
    return asyncio.run(
        review_module.save_and_revalidate(
            session=session,  # type: ignore[arg-type]
            order_id=ORDER_ID,
            candidate=make_candidate() if candidate is None else candidate,
            if_match=current_etag() if etag is _DEFAULT_ETAG else etag,  # type: ignore[arg-type]
            operator=operator,
            provider=provider or RecordingProvider(session, make_business_data()),
            policy=POLICY,
            date_provider=date_provider or FixedDateProvider(),
            recorded_at=RECORDED_AT,
        )
    )


def install_engine(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
    result: ValidationResult,
) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []

    def validate(*args: object) -> ValidationResult:
        assert not session.in_transaction()
        calls.append(args)
        return result

    monkeypatch.setattr(review_module.validation_engine, "validate", validate)
    return calls


def test_clean_revalidation_uses_candidate_and_commits_trusted_promotion_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session)
    repos.install(monkeypatch)
    candidate = make_candidate()
    provider = RecordingProvider(session, make_business_data())
    date_provider = FixedDateProvider()
    validation_result = make_clean_result(high_value=True)
    engine_calls = install_engine(monkeypatch, session, validation_result)

    result = call_service(
        session,
        candidate,
        provider=provider,
        date_provider=date_provider,
    )

    assert len(provider.calls) == 1
    assert provider.calls[0] == BusinessDataLookupRequest(
        customer_reference="CUST-001", customer_name=None, skus=("SKU-001",)
    )
    assert len(engine_calls) == 1
    composed, trusted, facts, policy, context = engine_calls[0]
    assert composed.po_number == "PO-101"
    assert composed.notes == "Keep original notes"
    assert composed.evidence == (Evidence("po_number", "page 1", "PO-100"),)
    assert composed.source_sha256 == SOURCE_SHA
    assert trusted is provider.result
    assert facts == ValidationFacts(False, False)
    assert policy is POLICY
    assert context == ValidationContext(EVALUATION_DATE)
    assert date_provider.calls == 1
    assert [open_state for open_state, _ in repos.fact_calls] == [False, True]
    assert [kwargs["canonical_customer_reference"] for _, kwargs in repos.fact_calls] == [
        "CUST-001",
        "CUST-001",
    ]
    assert session.rollback_count == 2
    assert session.commit_count == 1
    assert session.write_rollback_count == 0
    assert len(repos.revisions) == 1
    revision = repos.revisions[0]
    assert revision.payload == candidate
    assert revision.actor == OPERATOR.actor
    assert revision.revision_number == 1
    assert revision.changes == (ReviewChange("po_number", "PO-100", "PO-101"),)
    assert repos.order_updates[0].state is OrderState.READY_FOR_APPROVAL
    assert repos.order_updates[0].customer_reference == "CUST-001"
    assert repos.graph_replacements[0].lines[0].trusted_catalogue_price == Decimal("12")
    assert repos.issue_sets[0][1] == validation_result.issues
    assert [event.event_type for event in repos.audits] == [
        "REVIEW_REVISION_RECORDED",
        "REVIEW_REVALIDATION_COMPLETED",
        "ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION",
    ]
    assert [event.description for event in repos.audits] == [
        "Human review revision recorded.",
        "Deterministic revalidation completed for the effective human review draft.",
        "Deterministic validation passed; elevated approval is required after human correction.",
    ]
    assert [event.actor for event in repos.audits] == [OPERATOR.actor] * 3
    assert [event.occurred_at for event in repos.audits] == [
        RECORDED_AT,
        RECORDED_AT + timedelta(microseconds=1),
        RECORDED_AT + timedelta(microseconds=2),
    ]
    assert result.state is OrderState.READY_FOR_APPROVAL
    assert result.failure_origin is None
    assert result.revision_id == revision.id
    assert result.etag == compute_review_etag(
        ORDER_ID,
        OrderState.READY_FOR_APPROVAL,
        None,
        1,
        revision.id,
        repos.audits[-1].id,
    )


def test_invalid_correction_persists_review_values_without_replacing_trusted_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session)
    repos.install(monkeypatch)
    invalid = make_invalid_result()
    install_engine(monkeypatch, session, invalid)

    result = call_service(session)

    assert session.commit_count == 1
    assert len(repos.revisions) == 1
    assert repos.revisions[0].payload == make_candidate()
    assert repos.issue_sets == [(ORDER_ID, invalid.issues)]
    assert repos.order_updates[0].state is OrderState.NEEDS_REVIEW
    assert repos.order_updates[0].customer_reference == "TRUSTED-OLD"
    assert repos.order_updates[0].lines == make_order().lines
    assert repos.graph_replacements == []
    assert [event.event_type for event in repos.audits] == [
        "REVIEW_REVISION_RECORDED",
        "REVIEW_REVALIDATION_COMPLETED",
        "ORDER_REMAINS_NEEDS_REVIEW",
    ]
    assert repos.audits[-1].description == (
        "Deterministic revalidation found blocking issues; human review remains required."
    )
    assert result.state is OrderState.NEEDS_REVIEW


def test_latest_revision_is_effective_and_revision_number_increments_under_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    prior = make_revision(number=4)
    repos = RecordingRepositories(session, latest_revision=prior)
    repos.install(monkeypatch)
    install_engine(monkeypatch, session, make_clean_result())
    candidate = replace(prior.payload, po_number="PO-101")

    result = call_service(session, candidate, etag=current_etag(prior))

    assert repos.revisions[0].revision_number == 5
    assert repos.revisions[0].changes == (ReviewChange("po_number", "PO-100", "PO-101"),)
    assert result.revision_number == 5
    assert session.commit_count == 1


def test_changed_order_lines_are_one_ordered_aggregate_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session)
    repos.install(monkeypatch)
    products = TrustedBusinessData(
        customer_candidates=make_business_data().customer_candidates,
        products_by_line=(
            make_business_data().products_by_line[0],
            TrustedProduct("SKU-002", "Gadget", True, "USD", Decimal("25"), Decimal("10")),
        ),
    )
    provider = RecordingProvider(session, products)
    install_engine(monkeypatch, session, make_clean_result())
    candidate = replace(
        make_candidate(),
        lines=(
            ReviewLine("SKU-001", "Corrected widget", Decimal("3"), Decimal("10")),
            ReviewLine("SKU-002", "Gadget", Decimal("1"), Decimal("25")),
        ),
    )

    call_service(session, candidate, provider=provider)

    changes = repos.revisions[0].changes
    assert tuple(change.field_path for change in changes) == ("po_number", "lines")
    assert changes[1].old_value == [
        {"sku": "SKU-001", "description": "Widget", "quantity": "2", "submitted_price": "10"}
    ]
    assert changes[1].new_value == [
        {
            "sku": "SKU-001",
            "description": "Corrected widget",
            "quantity": "3",
            "submitted_price": "10",
        },
        {"sku": "SKU-002", "description": "Gadget", "quantity": "1", "submitted_price": "25"},
    ]


def test_review_time_date_provider_is_captured_once_and_drives_date_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session)
    repos.install(monkeypatch)
    date_provider = FixedDateProvider(date(2030, 3, 1))

    result = call_service(session, date_provider=date_provider)

    assert date_provider.calls == 1
    assert result.validation_result.route is ValidationRoute.NEEDS_REVIEW
    assert "DELIVERY_DATE_IN_PAST" in {issue.rule_code for issue in result.validation_result.issues}


def test_locked_state_change_aborts_without_writes_or_engine_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session)
    repos.orders = [make_persisted_order(), make_persisted_order(OrderState.READY_FOR_APPROVAL)]
    repos.install(monkeypatch)
    engine_calls = install_engine(monkeypatch, session, make_clean_result())

    with pytest.raises(InvalidReviewStateError):
        call_service(session)

    assert len(engine_calls) == 1
    assert session.commit_count == 0
    assert session.write_rollback_count == 1
    assert repos.revisions == []
    assert repos.audits == []


@pytest.mark.parametrize(
    ("operator", "candidate_mode", "tag_mode", "state", "error"),
    (
        (
            OperatorContext("approver", OperatorRole.APPROVER),
            "changed",
            "current",
            OrderState.NEEDS_REVIEW,
            ForbiddenError,
        ),
        (OPERATOR, "changed", "missing", OrderState.NEEDS_REVIEW, ReviewPreconditionRequiredError),
        (OPERATOR, "changed", "malformed", OrderState.NEEDS_REVIEW, ReviewPreconditionFailedError),
        (OPERATOR, "changed", "stale", OrderState.NEEDS_REVIEW, ReviewPreconditionFailedError),
        (OPERATOR, "changed", "current", OrderState.READY_FOR_APPROVAL, InvalidReviewStateError),
        (OPERATOR, "noop", "current", OrderState.NEEDS_REVIEW, NoReviewChangesError),
    ),
)
def test_early_rejections_stop_before_provider_and_close_preflight(
    monkeypatch: pytest.MonkeyPatch,
    operator: OperatorContext,
    candidate_mode: str,
    tag_mode: str,
    state: OrderState,
    error: type[Exception],
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session, order=make_persisted_order(state))
    repos.install(monkeypatch)
    provider = RecordingProvider(session, make_business_data())
    actual_candidate = (
        make_original_review_draft() if candidate_mode == "noop" else make_candidate()
    )
    supplied_tag: object = {
        "missing": None,
        "malformed": 'W/"weak"',
        "stale": '"' + "0" * 64 + '"',
        "current": current_etag(order=make_order(state)),
    }[tag_mode]

    with pytest.raises(error):
        call_service(
            session,
            actual_candidate,
            etag=supplied_tag,
            operator=operator,
            provider=provider,
        )

    assert provider.calls == []
    assert repos.revisions == []
    assert repos.audits == []
    assert session.commit_count == 0
    if operator.role is OperatorRole.REVIEWER:
        assert session.rollback_count == 1


def test_preflight_missing_order_rolls_back_and_skips_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session)
    repos.orders[0] = None  # type: ignore[assignment]
    repos.install(monkeypatch)
    provider = RecordingProvider(session, make_business_data())

    with pytest.raises(OrderNotFoundError):
        call_service(session, provider=provider)

    assert provider.calls == []
    assert session.rollback_count == 1


def test_preflight_rejects_missing_or_inconsistent_snapshot_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for snapshots in ((), (make_snapshot(), make_snapshot())):
        session = FakeSession()
        repos = RecordingRepositories(session, snapshots=snapshots)
        repos.install(monkeypatch)
        provider = RecordingProvider(session, make_business_data())

        with pytest.raises(ReviewCaseUnavailableError):
            call_service(session, provider=provider)

        assert provider.calls == []
        assert session.rollback_count == 1


@pytest.mark.parametrize("failure", ("provider", "provider_contract"))
def test_provider_failures_are_safe_and_do_not_reach_engine(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(session)
    repos.install(monkeypatch)
    engine_calls = install_engine(monkeypatch, session, make_clean_result())

    class FailingProvider(RecordingProvider):
        async def get_validation_data(
            self, request: BusinessDataLookupRequest
        ) -> TrustedBusinessData:
            assert not self.session.in_transaction()
            self.calls.append(request)
            if failure == "provider_contract":
                from opsflow.validation.business_data import TrustedBusinessDataContractError

                raise TrustedBusinessDataContractError("private malformed payload")
            raise RuntimeError("provider credential leaked")

    provider = FailingProvider(session, make_business_data())
    error = InvalidTrustedDataError if failure == "provider_contract" else BusinessDataProviderError

    with pytest.raises(error) as raised:
        call_service(session, provider=provider)

    assert "private" not in str(raised.value)
    assert "credential" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert len(provider.calls) == 1
    assert engine_calls == []
    assert session.rollback_count == 1
    assert not session.in_transaction()


def test_facts_staleness_rolls_back_without_engine_replay_or_partial_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(
        session,
        facts=(ValidationFacts(False, False), ValidationFacts(False, True)),
    )
    repos.install(monkeypatch)
    engine_calls = install_engine(monkeypatch, session, make_clean_result())

    with pytest.raises(ValidationFactsChangedError):
        call_service(session)

    assert len(engine_calls) == 1
    assert [open_state for open_state, _ in repos.fact_calls] == [False, True]
    assert session.commit_count == 0
    assert session.write_rollback_count == 1
    assert repos.revisions == []
    assert repos.issue_sets == []
    assert repos.order_updates == []
    assert repos.graph_replacements == []
    assert repos.audits == []


@pytest.mark.parametrize("changed_generation", ("revision", "audit"))
def test_final_etag_recheck_rejects_new_revision_or_audit_generation(
    monkeypatch: pytest.MonkeyPatch,
    changed_generation: str,
) -> None:
    session = FakeSession()
    prior = make_revision()
    repos = RecordingRepositories(session, latest_revision=None, audit_id=AUDIT_ID)
    repos.latest_revisions = [None, prior if changed_generation == "revision" else None]
    repos.audit_ids = [AUDIT_ID, UUID(int=106) if changed_generation == "audit" else AUDIT_ID]
    repos.install(monkeypatch)
    engine_calls = install_engine(monkeypatch, session, make_clean_result())

    with pytest.raises(ReviewPreconditionFailedError):
        call_service(session)

    assert len(engine_calls) == 1
    assert session.commit_count == 0
    assert session.write_rollback_count == 1
    assert repos.revisions == []
    assert repos.audits == []


def test_final_source_or_snapshot_change_is_rejected_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    original = make_snapshot()
    changed = make_snapshot(replace(original.draft, source_sha256="b" * 64))
    repos = RecordingRepositories(session, snapshots=(original,))
    repos.snapshots = [(original,), (changed,)]
    repos.install(monkeypatch)
    engine_calls = install_engine(monkeypatch, session, make_clean_result())

    with pytest.raises(ReviewCaseUnavailableError):
        call_service(session)

    assert len(engine_calls) == 1
    assert session.commit_count == 0
    assert session.write_rollback_count == 1
    assert repos.revisions == []
    assert repos.audits == []


@pytest.mark.parametrize(
    ("candidates", "expected_reference"),
    (
        ((), None),
        ((TrustedCustomer("CUST-1", "Acme Industries", False),), None),
        ((TrustedCustomer("CUST-1", "Acme Industries", True),), "CUST-1"),
        (
            (
                TrustedCustomer("CUST-1", "Acme Industries", True),
                TrustedCustomer("CUST-2", "Acme Industries", True),
            ),
            None,
        ),
        (
            (
                TrustedCustomer("CUST-1", "Acme Industries", True),
                TrustedCustomer("CUST-2", "Acme Industries", False),
            ),
            None,
        ),
    ),
)
def test_canonical_customer_reference_requires_one_total_active_candidate(
    candidates: tuple[TrustedCustomer, ...],
    expected_reference: str | None,
) -> None:
    assert (
        review_module.canonical_customer_reference(TrustedBusinessData(candidates, ()))
        == expected_reference
    )


def test_mixed_customer_candidates_remain_ambiguous_and_facts_identity_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    repos = RecordingRepositories(
        session,
        facts=(ValidationFacts(False, True), ValidationFacts(False, True)),
    )
    repos.install(monkeypatch)
    ambiguous = TrustedBusinessData(
        customer_candidates=(
            TrustedCustomer("CUST-1", "Acme Industries", True),
            TrustedCustomer("CUST-2", "Acme Industries", False),
        ),
        products_by_line=make_business_data().products_by_line,
    )
    provider = RecordingProvider(session, ambiguous)
    candidate = replace(make_candidate(), customer_reference=None)
    engine_calls: list[tuple[object, ...]] = []
    # Preserve the real Phase 5 engine while observing its exact input.
    from opsflow.validation.engine import validate as phase5_validate

    monkeypatch.setattr(
        review_module.validation_engine,
        "validate",
        lambda *args: _record_real_validation(engine_calls, session, phase5_validate, args),
    )

    result = call_service(session, candidate, provider=provider)

    assert len(provider.calls) == 1
    assert len(engine_calls) == 1
    assert engine_calls[0][1] is ambiguous
    assert [kwargs["canonical_customer_reference"] for _, kwargs in repos.fact_calls] == [
        None,
        None,
    ]
    assert [kwargs["po_number"] for _, kwargs in repos.fact_calls] == ["PO-101", "PO-101"]
    assert repos.fact_calls[0][1]["source_sha256"] == SOURCE_SHA
    assert repos.fact_calls[0][1]["source_document_id"] == SOURCE_ID
    assert result.state is OrderState.NEEDS_REVIEW
    issue_codes = {issue.rule_code for issue in repos.issue_sets[0][1]}
    assert "AMBIGUOUS_CUSTOMER" in issue_codes
    assert "DOCUMENT_ALREADY_PROCESSED" in issue_codes
    assert "DUPLICATE_CUSTOMER_PO" not in issue_codes


def _record_real_validation(
    calls: list[tuple[object, ...]],
    session: FakeSession,
    validate: object,
    args: tuple[object, ...],
) -> ValidationResult:
    assert not session.in_transaction()
    calls.append(args)
    return validate(*args)  # type: ignore[operator]
