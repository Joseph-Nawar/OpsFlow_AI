"""Focused review-read projection, authorization, and provider-boundary tests."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

import opsflow.application.review_reads as reads
import opsflow.persistence.repositories as repositories
from opsflow.api.review_schemas import review_detail_response
from opsflow.application.errors import (
    BusinessDataProviderError,
    ForbiddenError,
    ReviewCaseUnavailableError,
    ReviewDraftUnavailableError,
)
from opsflow.domain import (
    Order,
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
from opsflow.validation import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


class FakeSession:
    def __init__(self) -> None:
        self.transaction_open = True
        self.rollback_calls = 0

    def in_transaction(self) -> bool:
        return self.transaction_open

    async def rollback(self) -> None:
        self.rollback_calls += 1
        self.transaction_open = False


class RecordingProvider:
    def __init__(self, data: TrustedBusinessData | Exception) -> None:
        self.data = data
        self.calls: list[BusinessDataLookupRequest] = []
        self.session: FakeSession | None = None

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        assert self.session is not None
        assert self.session.in_transaction() is False
        self.calls.append(request)
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def test_queue_defaults_validate_bounds_and_require_view_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_queue_defaults(monkeypatch))


def test_queue_repository_aggregates_issue_signals_in_one_bounded_page_query() -> None:
    asyncio.run(_assert_queue_repository_query_shape())


def test_review_detail_projects_original_and_latest_revision_and_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_detail_projection(monkeypatch))


@pytest.mark.parametrize(
    ("state", "role", "high_value", "expected"),
    [
        (OrderState.NEEDS_REVIEW, OperatorRole.REVIEWER, False, (True, False, True, False)),
        (OrderState.NEEDS_REVIEW, OperatorRole.APPROVER, False, (False, False, False, False)),
        (OrderState.READY_FOR_APPROVAL, OperatorRole.APPROVER, False, (False, True, True, False)),
        (OrderState.READY_FOR_APPROVAL, OperatorRole.APPROVER, True, (False, False, True, False)),
        (
            OrderState.READY_FOR_APPROVAL,
            OperatorRole.ELEVATED_APPROVER,
            True,
            (False, True, True, False),
        ),
        (
            OrderState.FAILED_RETRYABLE,
            OperatorRole.REVIEWER,
            False,
            (False, False, False, True),
        ),
    ],
)
def test_review_detail_action_matrix(
    monkeypatch: pytest.MonkeyPatch,
    state: OrderState,
    role: OperatorRole,
    high_value: bool,
    expected: tuple[bool, bool, bool, bool],
) -> None:
    asyncio.run(_assert_action_matrix(monkeypatch, state, role, high_value, expected))


def test_review_detail_allows_pre_extraction_retry_without_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_pre_extraction_detail(monkeypatch, OrderState.PROCESSING))


def test_review_detail_allows_extracted_stage_retry_before_snapshot_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_pre_extraction_detail(monkeypatch, OrderState.EXTRACTED))


def test_review_detail_rejects_missing_expected_or_multiple_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_bad_snapshots(monkeypatch))


def test_reference_data_provider_runs_once_after_read_transaction_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_provider_boundary(monkeypatch))


def test_reference_data_provider_failure_is_safe_and_leaves_session_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_provider_failure(monkeypatch))


def test_reference_data_without_effective_draft_closes_session_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_missing_effective_draft(monkeypatch))


async def _assert_queue_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    async def list_rows(session: object, states: tuple[OrderState, ...], limit: int, offset: int):
        observed.update(states=states, limit=limit, offset=offset)
        return (), 0

    monkeypatch.setattr(reads, "list_review_order_summaries", list_rows)
    operator = OperatorContext("reviewer-demo", OperatorRole.REVIEWER)
    page = await reads.list_review_orders(FakeSession(), None, 50, 0, operator)
    assert page.states == (
        OrderState.NEEDS_REVIEW,
        OrderState.READY_FOR_APPROVAL,
        OrderState.FAILED_RETRYABLE,
    )
    assert observed == {"states": page.states, "limit": 50, "offset": 0}
    approver_page = await reads.list_review_orders(
        FakeSession(), None, 50, 0, OperatorContext("approver", OperatorRole.APPROVER)
    )
    assert approver_page.states == page.states

    with pytest.raises(ValueError):
        await reads.list_review_orders(FakeSession(), (OrderState.APPROVED,), 50, 0, operator)
    with pytest.raises(ValueError):
        await reads.list_review_orders(FakeSession(), None, 101, 0, operator)
    with pytest.raises(ValueError):
        await reads.list_review_orders(FakeSession(), None, 50, -1, operator)
    with pytest.raises(ForbiddenError):
        await reads.list_review_orders(FakeSession(), None, 50, 0, cast(OperatorContext, object()))


async def _assert_queue_repository_query_shape() -> None:
    class CapturingSession:
        def __init__(self) -> None:
            self.statements: list[object] = []
            self.scalar_calls = 0

        async def scalar(self, statement: object) -> int:
            self.scalar_calls += 1
            return 0

        async def execute(self, statement: object) -> object:
            self.statements.append(statement)

            class Rows:
                def all(self) -> list[object]:
                    return []

            return Rows()

    session = CapturingSession()
    rows, total = await repositories.list_review_order_summaries(
        session,
        (OrderState.NEEDS_REVIEW, OrderState.READY_FOR_APPROVAL),
        25,
        10,
    )
    statement = session.statements[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert rows == ()
    assert total == 0
    assert session.scalar_calls == 1
    assert len(session.statements) == 1
    assert "bool_or" in sql
    assert "GROUP BY validation_issues.order_id" in sql
    assert "ORDER BY orders.created_at ASC, orders.id ASC" in sql
    assert statement._limit_clause is not None
    assert statement._offset_clause is not None


async def _assert_detail_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    persisted, snapshot, revision_one_fixture = _review_case(OrderState.NEEDS_REVIEW)
    revision = replace(revision_one_fixture, revision_number=2)
    first_revision = ReviewRevision(
        uuid4(),
        persisted.order.id,
        snapshot.id,
        1,
        ReviewDraft("Old Acme", "CUST-1", "PO-1", date(2026, 9, 1), date(2026, 10, 1), "USD", ()),
        (ReviewChange("customer_name", "Acme", "Old Acme"),),
        "reviewer",
        NOW,
    )
    audit_id = uuid4()
    _stub_detail_reads(
        monkeypatch,
        persisted,
        (snapshot,),
        revision,
        (first_revision, revision),
        audit_id,
    )

    result = await reads.get_review_detail(
        FakeSession(), persisted.order.id, OperatorContext("reviewer", OperatorRole.REVIEWER)
    )
    assert result.source_snapshot == snapshot
    assert result.effective_draft == revision.payload
    assert result.latest_revision == revision
    assert result.revisions == (first_revision, revision)
    assert result.actions.can_edit is True
    assert result.actions.can_approve is False
    assert result.etag.startswith('"') and result.etag.endswith('"')


def test_detail_uses_original_projection_without_revisions_and_checks_source_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_original_projection_and_source_ownership(monkeypatch))


def test_detail_wire_mapping_keeps_original_evidence_separate_from_human_draft() -> None:
    persisted, snapshot, revision = _review_case(OrderState.NEEDS_REVIEW)
    result = reads.ReviewDetailData(
        order=persisted,
        source_snapshot=snapshot,
        effective_draft=revision.payload,
        revisions=(revision,),
        latest_revision=revision,
        actions=reads.ReviewActions(True, False, True, False),
        operator=OperatorContext("reviewer", OperatorRole.REVIEWER),
        etag='"' + "a" * 64 + '"',
    )
    wire = review_detail_response(result).model_dump(mode="json")
    assert wire["original_extraction"]["evidence"][0]["quote"] == "Acme"
    assert wire["effective_draft"]["customer_name"] == "Acme"
    assert wire["source_snapshot"]["id"] == str(snapshot.id)
    assert wire["operator"] == {"actor": "reviewer", "role": "REVIEWER"}
    assert "audit_events" not in wire


async def _assert_action_matrix(
    monkeypatch: pytest.MonkeyPatch,
    state: OrderState,
    role: OperatorRole,
    high_value: bool,
    expected: tuple[bool, bool, bool, bool],
) -> None:
    persisted, snapshot, revision = _review_case(state, high_value=high_value)
    _stub_detail_reads(monkeypatch, persisted, (snapshot,), revision, (revision,), uuid4())
    detail = await reads.get_review_detail(
        FakeSession(), persisted.order.id, OperatorContext("operator", role)
    )
    assert (
        detail.actions.can_edit,
        detail.actions.can_approve,
        detail.actions.can_reject,
        detail.actions.can_retry,
    ) == expected


async def _assert_pre_extraction_detail(
    monkeypatch: pytest.MonkeyPatch,
    failure_origin: OrderState,
) -> None:
    persisted = PersistedOrder(
        order=Order(
            id=uuid4(),
            state=OrderState.FAILED_RETRYABLE,
            failure_origin=failure_origin,
        ),
        created_at=NOW,
        validation_issues=(),
    )
    _stub_detail_reads(monkeypatch, persisted, (), None, (), None)
    result = await reads.get_review_detail(
        FakeSession(), persisted.order.id, OperatorContext("reviewer", OperatorRole.REVIEWER)
    )
    assert result.source_snapshot is None
    assert result.effective_draft is None
    assert result.actions.can_retry is True


async def _assert_bad_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    persisted, snapshot, _ = _review_case(OrderState.NEEDS_REVIEW)
    _stub_detail_reads(monkeypatch, persisted, (), None, (), None)
    with pytest.raises(ReviewCaseUnavailableError):
        await reads.get_review_detail(
            FakeSession(), persisted.order.id, OperatorContext("reviewer", OperatorRole.REVIEWER)
        )
    _stub_detail_reads(monkeypatch, persisted, (snapshot, snapshot), None, (), None)
    with pytest.raises(ReviewCaseUnavailableError):
        await reads.get_review_detail(
            FakeSession(), persisted.order.id, OperatorContext("reviewer", OperatorRole.REVIEWER)
        )


async def _assert_original_projection_and_source_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted, snapshot, _ = _review_case(OrderState.NEEDS_REVIEW)
    _stub_detail_reads(monkeypatch, persisted, (snapshot,), None, (), uuid4())
    detail = await reads.get_review_detail(
        FakeSession(), persisted.order.id, OperatorContext("reviewer", OperatorRole.REVIEWER)
    )
    assert detail.effective_draft == reads.review_draft_from_extraction(snapshot.draft)

    wrong_source = PersistedExtractionSnapshot(
        snapshot.id,
        snapshot.order_id,
        uuid4(),
        snapshot.source_sha256,
        snapshot.source_document_type,
        snapshot.draft,
        snapshot.created_at,
    )
    _stub_detail_reads(monkeypatch, persisted, (wrong_source,), None, (), None)
    with pytest.raises(ReviewCaseUnavailableError):
        await reads.get_review_detail(
            FakeSession(), persisted.order.id, OperatorContext("reviewer", OperatorRole.REVIEWER)
        )


async def _assert_provider_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    persisted, snapshot, revision = _review_case(OrderState.NEEDS_REVIEW)
    _stub_detail_reads(monkeypatch, persisted, (snapshot,), revision, (revision,), uuid4())
    session = FakeSession()
    data = TrustedBusinessData(
        customer_candidates=(TrustedCustomer("CUST-1", "Acme", True),),
        products_by_line=(
            TrustedProduct("SKU-1", "Widget", True, "USD", Decimal("10"), Decimal("5")),
        ),
    )
    provider = RecordingProvider(data)
    provider.session = session
    result = await reads.get_current_reference_data(
        session,
        persisted.order.id,
        OperatorContext("reviewer", OperatorRole.REVIEWER),
        provider,
    )
    assert result == data
    assert provider.calls == [BusinessDataLookupRequest("CUST-1", None, ("SKU-1",))]
    assert session.rollback_calls == 1
    assert session.in_transaction() is False


async def _assert_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    persisted, snapshot, revision = _review_case(OrderState.NEEDS_REVIEW)
    _stub_detail_reads(monkeypatch, persisted, (snapshot,), revision, (revision,), uuid4())
    session = FakeSession()
    provider = RecordingProvider(RuntimeError("private provider detail"))
    provider.session = session
    with pytest.raises(BusinessDataProviderError) as error:
        await reads.get_current_reference_data(
            session,
            persisted.order.id,
            OperatorContext("reviewer", OperatorRole.REVIEWER),
            provider,
        )
    assert str(error.value) == "Business data provider operation failed."
    assert provider.calls
    assert session.in_transaction() is False


async def _assert_missing_effective_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    persisted = PersistedOrder(
        order=Order(
            id=uuid4(),
            state=OrderState.FAILED_RETRYABLE,
            failure_origin=OrderState.PROCESSING,
        ),
        created_at=NOW,
        validation_issues=(),
    )
    _stub_detail_reads(monkeypatch, persisted, (), None, (), None)
    session = FakeSession()
    provider = RecordingProvider(TrustedBusinessData((), ()))
    provider.session = session
    with pytest.raises(ReviewDraftUnavailableError):
        await reads.get_current_reference_data(
            session,
            persisted.order.id,
            OperatorContext("reviewer", OperatorRole.REVIEWER),
            provider,
        )
    assert session.rollback_calls == 1
    assert provider.calls == []


def _stub_detail_reads(
    monkeypatch: pytest.MonkeyPatch,
    persisted: PersistedOrder,
    snapshots: tuple[PersistedExtractionSnapshot, ...],
    latest: object,
    history: tuple[object, ...],
    audit_id: object,
) -> None:
    async def get_order(session: object, order_id: object) -> PersistedOrder:
        assert order_id == persisted.order.id
        return persisted

    async def get_snapshots(session: object, order_id: object):
        assert order_id == persisted.order.id
        return snapshots

    async def get_latest(session: object, order_id: object):
        return latest

    async def get_history(session: object, order_id: object):
        return history

    async def get_audit_id(session: object, order_id: object):
        return audit_id

    monkeypatch.setattr(reads, "get_order", get_order)
    monkeypatch.setattr(reads, "get_extraction_snapshots_for_order", get_snapshots)
    monkeypatch.setattr(reads, "get_latest_review_revision", get_latest)
    monkeypatch.setattr(reads, "get_review_revision_history", get_history)
    monkeypatch.setattr(reads, "get_latest_audit_event_id", get_audit_id)


def _review_case(
    state: OrderState,
    *,
    high_value: bool = False,
) -> tuple[PersistedOrder, PersistedExtractionSnapshot, object]:
    order_id = uuid4()
    source_id = uuid4()
    snapshot_id = uuid4()
    source = SourceDocument(
        source_id,
        SourceDocumentType.PDF,
        "purchase-order.pdf",
        "application/pdf",
        "a" * 64,
        None,
        "synthetic://purchase-order.pdf",
        (),
    )
    order = Order(
        id=order_id,
        source_documents=(source,),
        state=state,
        failure_origin=OrderState.SYNCING if state is OrderState.FAILED_RETRYABLE else None,
    )
    issue = (
        (
            ValidationIssue(
                "HIGH_VALUE_APPROVAL_REQUIRED",
                ValidationSeverity.WARNING,
                None,
                None,
                None,
                "Synthetic high-value threshold was exceeded.",
            ),
        )
        if high_value
        else ()
    )
    persisted = PersistedOrder(order=order, created_at=NOW, validation_issues=issue)
    original = ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme",
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2026, 9, 1),
        requested_delivery_date=date(2026, 10, 1),
        currency="USD",
        lines=(ExtractedLine("SKU-1", "Widget", Decimal("1"), Decimal("10")),),
        notes="original extraction note",
        evidence=(Evidence("customer_name", "page 1", "Acme"),),
    )
    snapshot = PersistedExtractionSnapshot(
        snapshot_id,
        order_id,
        source_id,
        "a" * 64,
        SourceDocumentType.PDF,
        original,
        NOW,
    )
    draft = ReviewDraft(
        "Acme",
        "CUST-1",
        "PO-1",
        date(2026, 9, 1),
        date(2026, 10, 1),
        "USD",
        (ReviewLine("SKU-1", "Widget", Decimal("1"), Decimal("10")),),
    )
    revision = ReviewRevision(
        uuid4(),
        order_id,
        snapshot_id,
        1,
        draft,
        (ReviewChange("customer_name", "Old Acme", "Acme"),),
        "reviewer",
        NOW,
    )
    return persisted, snapshot, revision
