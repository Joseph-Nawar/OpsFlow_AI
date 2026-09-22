"""Unit coverage for Phase 6 approval, rejection, and retry commands."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

import opsflow.application.review_commands as commands
from opsflow.application.errors import (
    ForbiddenError,
    InvalidRejectionReasonError,
    InvalidReviewStateError,
    OrderNotFoundError,
    ReviewPreconditionFailedError,
    ReviewPreconditionRequiredError,
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

ORDER_ID = UUID(int=601)
LINE_ID = UUID(int=602)
SOURCE_ID = UUID(int=603)
INITIAL_AUDIT_ID = UUID(int=604)
NOW = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
REVIEWER = OperatorContext("reviewer-actor", OperatorRole.REVIEWER)
APPROVER = OperatorContext("approver-actor", OperatorRole.APPROVER)
ELEVATED = OperatorContext("elevated-actor", OperatorRole.ELEVATED_APPROVER)
_CURRENT_ETAG = object()


def _source() -> SourceDocument:
    return SourceDocument(
        id=SOURCE_ID,
        document_type=SourceDocumentType.PDF,
        name="order.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        message_id=None,
        storage_reference=None,
        metadata=(),
    )


def _order(
    state: OrderState,
    *,
    failure_origin: OrderState | None = None,
) -> Order:
    return Order(
        id=ORDER_ID,
        customer_reference="CUST-001",
        po_number="PO-001",
        currency="USD",
        lines=(
            OrderLine(
                LINE_ID,
                "SKU-001",
                "Widget",
                Decimal("2"),
                Decimal("10"),
                Decimal("10"),
            ),
        ),
        source_documents=(_source(),),
        state=state,
        failure_origin=failure_origin,
    )


def _high_value_issue(severity: ValidationSeverity = ValidationSeverity.WARNING) -> ValidationIssue:
    return ValidationIssue(
        rule_code="HIGH_VALUE_APPROVAL_REQUIRED",
        severity=severity,
        field="order_total",
        expected=Decimal("1000"),
        actual=Decimal("1200"),
        explanation="Elevated approval is required.",
    )


def _revision(number: int, revision_id: UUID) -> ReviewRevision:
    return ReviewRevision(
        id=revision_id,
        order_id=ORDER_ID,
        extraction_snapshot_id=UUID(int=607),
        revision_number=number,
        payload=ReviewDraft(
            "Acme",
            "CUST-001",
            "PO-002",
            None,
            None,
            "USD",
            (ReviewLine("SKU-001", "Widget", Decimal("2"), Decimal("10")),),
        ),
        changes=(ReviewChange("po_number", "PO-001", "PO-002"),),
        actor="reviewer-prior",
        created_at=NOW,
    )


class FakeSession:
    """Model SQLAlchemy autobegin, explicit preflight rollback, and one write txn."""

    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.transaction_open = False
        self.rollback_count = 0
        self.commit_count = 0
        self.write_rollback_count = 0

    def in_transaction(self) -> bool:
        return self.transaction_open

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.transaction_open = False
        self.store.operations.append("rollback")

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.snapshot: tuple[PersistedOrder, list[AuditEvent], UUID | None] | None = None

    async def __aenter__(self) -> FakeSession:
        assert self.session.in_transaction() is False
        self.snapshot = (
            self.session.store.persisted,
            list(self.session.store.audit_events),
            self.session.store.latest_audit_id,
        )
        self.session.transaction_open = True
        self.session.store.operations.append("begin")
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.session.commit_count += 1
            self.session.store.operations.append("commit")
        else:
            assert self.snapshot is not None
            (
                self.session.store.persisted,
                self.session.store.audit_events,
                self.session.store.latest_audit_id,
            ) = self.snapshot
            self.session.write_rollback_count += 1
            self.session.store.operations.append("write_rollback")
        self.session.transaction_open = False


class FakeStore:
    def __init__(
        self,
        state: OrderState = OrderState.READY_FOR_APPROVAL,
        *,
        failure_origin: OrderState | None = None,
        issues: tuple[ValidationIssue, ...] = (),
        latest_revision: ReviewRevision | None = None,
    ) -> None:
        self.persisted = PersistedOrder(_order(state, failure_origin=failure_origin), NOW, issues)
        self.latest_revision = latest_revision
        self.latest_audit_id: UUID | None = INITIAL_AUDIT_ID
        self.audit_events: list[AuditEvent] = []
        self.operations: list[str] = []
        self.on_lock: Callable[[FakeStore], None] | None = None
        self.fail_event_type: str | None = None
        self.order_reads = 0
        self.audit_reads = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def get_order(session: FakeSession, order_id: UUID) -> PersistedOrder | None:
            self._begin_read(session)
            self.operations.append("get_order")
            self.order_reads += 1
            return self.persisted if order_id == ORDER_ID else None

        async def get_order_for_update(
            session: FakeSession, order_id: UUID
        ) -> PersistedOrder | None:
            assert session.in_transaction()
            self.operations.append("get_order_for_update")
            if self.on_lock is not None:
                self.on_lock(self)
            return self.persisted if order_id == ORDER_ID else None

        async def get_latest_review_revision(
            session: FakeSession, order_id: UUID
        ) -> ReviewRevision | None:
            self._begin_read(session)
            self.operations.append("get_latest_review_revision")
            return self.latest_revision

        async def get_latest_audit_event_id(session: FakeSession, order_id: UUID) -> UUID | None:
            assert session.in_transaction()
            self.operations.append("get_latest_audit_event_id")
            self.audit_reads += 1
            return self.latest_audit_id

        async def update_order_snapshot(session: FakeSession, order: Order) -> None:
            assert session.in_transaction()
            self.operations.append("update_order_snapshot")
            self.persisted = PersistedOrder(
                order,
                self.persisted.created_at,
                self.persisted.validation_issues,
            )

        async def insert_audit_event(session: FakeSession, event: AuditEvent) -> None:
            assert session.in_transaction()
            self.operations.append(f"insert:{event.event_type}")
            if event.event_type == self.fail_event_type:
                raise RuntimeError("simulated audit persistence failure")
            self.audit_events.append(event)
            self.latest_audit_id = event.id

        monkeypatch.setattr(commands, "get_order", get_order)
        monkeypatch.setattr(commands, "get_order_for_update", get_order_for_update)
        monkeypatch.setattr(commands, "get_latest_review_revision", get_latest_review_revision)
        monkeypatch.setattr(commands, "get_latest_audit_event_id", get_latest_audit_event_id)
        monkeypatch.setattr(commands, "update_order_snapshot", update_order_snapshot)
        monkeypatch.setattr(commands, "insert_audit_event", insert_audit_event)

    @staticmethod
    def _begin_read(session: FakeSession) -> None:
        if not session.in_transaction():
            session.transaction_open = True


def _etag(store: FakeStore) -> str:
    order = store.persisted.order
    revision = store.latest_revision
    return compute_review_etag(
        order.id,
        order.state,
        order.failure_origin,
        revision.revision_number if revision is not None else None,
        revision.id if revision is not None else None,
        store.latest_audit_id,
    )


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    store: FakeStore,
    operation: str,
    *,
    operator: OperatorContext,
    if_match: str | None | object = _CURRENT_ETAG,
    reason: str = "Approved after review",
) -> tuple[object, FakeSession]:
    store.install(monkeypatch)
    session = FakeSession(store)
    current = _etag(store) if if_match is _CURRENT_ETAG else if_match
    if operation == "approve":
        result = asyncio.run(
            commands.approve_order(session, ORDER_ID, current, operator, NOW)  # type: ignore[arg-type]
        )
    elif operation == "reject":
        result = asyncio.run(
            commands.reject_order(
                session,
                ORDER_ID,
                reason,
                current,
                operator,
                NOW,  # type: ignore[arg-type]
            )
        )
    else:
        result = asyncio.run(
            commands.retry_order(session, ORDER_ID, current, operator, NOW)  # type: ignore[arg-type]
        )
    return result, session


@pytest.mark.parametrize("operator", [APPROVER, ELEVATED])
def test_ordinary_ready_order_is_approved_and_audited(
    monkeypatch: pytest.MonkeyPatch, operator: OperatorContext
) -> None:
    store = FakeStore()
    old_etag = _etag(store)

    result, session = _invoke(monkeypatch, store, "approve", operator=operator)

    assert store.persisted.order.state is OrderState.APPROVED
    assert result.state is OrderState.APPROVED  # type: ignore[attr-defined]
    assert result.failure_origin is None  # type: ignore[attr-defined]
    assert len(store.audit_events) == 1
    assert (
        store.audit_events[0].event_type,
        store.audit_events[0].actor,
        store.audit_events[0].description,
        store.audit_events[0].occurred_at,
    ) == ("ORDER_APPROVED", operator.actor, "Order approved by operator.", NOW)
    assert result.etag == _etag(store)  # type: ignore[attr-defined]
    assert result.etag != old_etag  # type: ignore[attr-defined]
    assert session.rollback_count == 1
    assert session.commit_count == 1
    assert session.write_rollback_count == 0
    assert store.operations.index("rollback") < store.operations.index("begin")


def test_command_preserves_the_existing_trusted_business_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(OrderState.FAILED_RETRYABLE, failure_origin=OrderState.EXTRACTED)
    original = store.persisted.order

    _invoke(monkeypatch, store, "retry", operator=REVIEWER)

    assert store.persisted.order == replace(
        original,
        state=OrderState.EXTRACTED,
        failure_origin=None,
    )


def test_reviewer_cannot_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    with pytest.raises(ForbiddenError):
        _invoke(monkeypatch, store, "approve", operator=REVIEWER)


def test_ordinary_approver_cannot_approve_persisted_high_value_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(issues=(_high_value_issue(),))

    with pytest.raises(ForbiddenError):
        _invoke(monkeypatch, store, "approve", operator=APPROVER)

    assert store.persisted.order.state is OrderState.READY_FOR_APPROVAL
    assert not store.audit_events


def test_high_value_approval_is_allowed_for_elevated_approver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(issues=(_high_value_issue(),))

    result, _ = _invoke(monkeypatch, store, "approve", operator=ELEVATED)

    assert result.state is OrderState.APPROVED  # type: ignore[attr-defined]


def test_high_value_rule_with_nonwarning_severity_does_not_restrict_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(issues=(_high_value_issue(ValidationSeverity.ERROR),))

    result, _ = _invoke(monkeypatch, store, "approve", operator=APPROVER)

    assert result.state is OrderState.APPROVED  # type: ignore[attr-defined]


def test_approver_final_lock_rechecks_persisted_high_value_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    store.on_lock = lambda current: setattr(
        current,
        "persisted",
        replace(current.persisted, validation_issues=(_high_value_issue(),)),
    )

    with pytest.raises(ForbiddenError):
        _invoke(monkeypatch, store, "approve", operator=APPROVER)

    assert store.persisted.order.state is OrderState.READY_FOR_APPROVAL
    assert not store.audit_events


def test_approval_rejects_non_ready_state_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(OrderState.NEEDS_REVIEW)

    with pytest.raises(InvalidReviewStateError):
        _invoke(monkeypatch, store, "approve", operator=APPROVER)

    assert store.persisted.order.state is OrderState.NEEDS_REVIEW
    assert not store.audit_events


@pytest.mark.parametrize(
    ("state", "operator", "allowed"),
    [
        (OrderState.NEEDS_REVIEW, REVIEWER, True),
        (OrderState.READY_FOR_APPROVAL, REVIEWER, False),
        (OrderState.READY_FOR_APPROVAL, APPROVER, True),
        (OrderState.READY_FOR_APPROVAL, ELEVATED, True),
        (OrderState.NEEDS_REVIEW, APPROVER, False),
        (OrderState.NEEDS_REVIEW, ELEVATED, False),
    ],
)
def test_rejection_enforces_exact_role_and_state_pair(
    monkeypatch: pytest.MonkeyPatch,
    state: OrderState,
    operator: OperatorContext,
    allowed: bool,
) -> None:
    store = FakeStore(state, issues=(_high_value_issue(),))

    if allowed:
        result, _ = _invoke(monkeypatch, store, "reject", operator=operator)
        assert result.state is OrderState.REJECTED  # type: ignore[attr-defined]
        assert store.audit_events[0].actor == operator.actor
    else:
        with pytest.raises(ForbiddenError):
            _invoke(monkeypatch, store, "reject", operator=operator)
        assert store.persisted.order.state is state
        assert not store.audit_events


def test_rejection_trims_reason_and_records_exact_audit_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(OrderState.NEEDS_REVIEW)

    result, session = _invoke(
        monkeypatch,
        store,
        "reject",
        operator=REVIEWER,
        reason="  incorrect customer  ",
    )

    event = store.audit_events[0]
    assert (event.event_type, event.actor, event.description, event.occurred_at) == (
        "ORDER_REJECTED",
        REVIEWER.actor,
        "Order rejected. Reason: incorrect customer",
        NOW,
    )
    assert result.state is OrderState.REJECTED  # type: ignore[attr-defined]
    assert session.commit_count == 1


@pytest.mark.parametrize("reason", ["", "  \t\n  ", "é" * 501])
def test_rejection_rejects_blank_or_overlong_reason_before_database_work(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    store = FakeStore(OrderState.NEEDS_REVIEW)
    session = FakeSession(store)
    store.install(monkeypatch)

    with pytest.raises(InvalidRejectionReasonError):
        asyncio.run(commands.reject_order(session, ORDER_ID, reason, _etag(store), REVIEWER, NOW))

    assert store.order_reads == 0
    assert not store.audit_events
    assert session.commit_count == 0


def test_rejection_accepts_exactly_500_unicode_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(OrderState.READY_FOR_APPROVAL)
    reason = "é" * 500

    result, _ = _invoke(monkeypatch, store, "reject", operator=APPROVER, reason=reason)

    assert result.state is OrderState.REJECTED  # type: ignore[attr-defined]
    assert store.audit_events[0].description == f"Order rejected. Reason: {reason}"


def test_rejection_requires_a_string_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(OrderState.NEEDS_REVIEW)
    session = FakeSession(store)
    store.install(monkeypatch)

    with pytest.raises(InvalidRejectionReasonError):
        asyncio.run(
            commands.reject_order(
                session,
                ORDER_ID,
                None,  # type: ignore[arg-type]
                _etag(store),
                REVIEWER,
                NOW,
            )
        )

    assert store.order_reads == 0
    assert not store.audit_events


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (OrderState.PROCESSING, OrderState.PROCESSING),
        (OrderState.EXTRACTED, OrderState.EXTRACTED),
        (OrderState.SYNCING, OrderState.SYNCING),
    ],
)
def test_retry_restores_only_persisted_failure_origin_and_audits_in_order(
    monkeypatch: pytest.MonkeyPatch,
    origin: OrderState,
    expected: OrderState,
) -> None:
    store = FakeStore(OrderState.FAILED_RETRYABLE, failure_origin=origin)
    old_etag = _etag(store)

    result, session = _invoke(monkeypatch, store, "retry", operator=REVIEWER)

    assert store.persisted.order.state is expected
    assert store.persisted.order.failure_origin is None
    assert [event.event_type for event in store.audit_events] == [
        "ORDER_RETRY_REQUESTED",
        "ORDER_RETRY_RESTORED",
    ]
    assert [event.description for event in store.audit_events] == [
        "Retry requested by operator.",
        "Retryable failure cleared; order restored to its recorded failure origin.",
    ]
    assert [event.actor for event in store.audit_events] == [REVIEWER.actor, REVIEWER.actor]
    assert [event.occurred_at for event in store.audit_events] == [
        NOW,
        NOW + timedelta(microseconds=1),
    ]
    assert result.state is expected  # type: ignore[attr-defined]
    assert result.failure_origin is None  # type: ignore[attr-defined]
    assert result.etag == _etag(store)  # type: ignore[attr-defined]
    assert result.etag != old_etag  # type: ignore[attr-defined]
    assert session.commit_count == 1


def test_retry_is_reviewer_only_and_requires_retryable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approver_store = FakeStore(OrderState.FAILED_RETRYABLE, failure_origin=OrderState.EXTRACTED)
    with pytest.raises(ForbiddenError):
        _invoke(monkeypatch, approver_store, "retry", operator=APPROVER)
    assert not approver_store.audit_events

    invalid_state_store = FakeStore(OrderState.EXTRACTED)
    with pytest.raises(InvalidReviewStateError):
        _invoke(monkeypatch, invalid_state_store, "retry", operator=REVIEWER)
    assert not invalid_state_store.audit_events


@pytest.mark.parametrize("operation", ["approve", "reject", "retry"])
def test_each_command_requires_a_well_formed_current_if_match(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    state = {
        "approve": OrderState.READY_FOR_APPROVAL,
        "reject": OrderState.NEEDS_REVIEW,
        "retry": OrderState.FAILED_RETRYABLE,
    }[operation]
    store = FakeStore(
        state,
        failure_origin=OrderState.EXTRACTED if state is OrderState.FAILED_RETRYABLE else None,
    )
    operator = REVIEWER if operation != "approve" else APPROVER

    with pytest.raises(ReviewPreconditionRequiredError):
        _invoke(monkeypatch, store, operation, operator=operator, if_match=None)


@pytest.mark.parametrize("operation", ["approve", "reject", "retry"])
@pytest.mark.parametrize("supplied_etag", ['W/"weak"', '"' + "0" * 64 + '"'])
def test_each_command_rejects_malformed_or_stale_if_match_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    supplied_etag: str,
) -> None:
    state = {
        "approve": OrderState.READY_FOR_APPROVAL,
        "reject": OrderState.NEEDS_REVIEW,
        "retry": OrderState.FAILED_RETRYABLE,
    }[operation]
    store = FakeStore(
        state,
        failure_origin=OrderState.EXTRACTED if state is OrderState.FAILED_RETRYABLE else None,
    )
    operator = REVIEWER if operation != "approve" else APPROVER

    with pytest.raises(ReviewPreconditionFailedError):
        _invoke(monkeypatch, store, operation, operator=operator, if_match=supplied_etag)

    assert not store.audit_events
    assert store.persisted.order.state is state
    assert store.order_reads == 1
    assert store.audit_reads == 1


@pytest.mark.parametrize("operation", ["approve", "reject", "retry"])
def test_missing_if_match_closes_preflight_read_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    state = {
        "approve": OrderState.READY_FOR_APPROVAL,
        "reject": OrderState.NEEDS_REVIEW,
        "retry": OrderState.FAILED_RETRYABLE,
    }[operation]
    store = FakeStore(
        state,
        failure_origin=OrderState.EXTRACTED if state is OrderState.FAILED_RETRYABLE else None,
    )
    session = FakeSession(store)
    store.install(monkeypatch)
    operator = REVIEWER if operation != "approve" else APPROVER

    with pytest.raises(ReviewPreconditionRequiredError):
        if operation == "approve":
            asyncio.run(commands.approve_order(session, ORDER_ID, None, operator, NOW))
        elif operation == "reject":
            asyncio.run(commands.reject_order(session, ORDER_ID, "reason", None, operator, NOW))
        else:
            asyncio.run(commands.retry_order(session, ORDER_ID, None, operator, NOW))

    assert session.rollback_count == 1
    assert session.in_transaction() is False
    assert session.commit_count == 0
    assert not store.audit_events


def test_changed_review_revision_invalidates_preflight_etag_under_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    store.on_lock = lambda current: setattr(
        current,
        "latest_revision",
        _revision(1, UUID(int=608)),
    )

    with pytest.raises(ReviewPreconditionFailedError):
        _invoke(monkeypatch, store, "approve", operator=APPROVER)

    assert store.persisted.order.state is OrderState.READY_FOR_APPROVAL
    assert not store.audit_events


def test_fresh_etag_preserves_latest_revision_and_uses_new_audit_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    store.latest_revision = _revision(3, UUID(int=609))

    result, _ = _invoke(monkeypatch, store, "approve", operator=APPROVER)

    assert result.etag == _etag(store)  # type: ignore[attr-defined]
    assert store.latest_revision.revision_number == 3
    assert store.latest_audit_id == store.audit_events[-1].id


@pytest.mark.parametrize("changed", ["state", "audit"])
def test_final_lock_rejects_changed_state_or_audit_generation(
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    store = FakeStore()
    if changed == "state":
        store.on_lock = lambda current: setattr(
            current,
            "persisted",
            replace(
                current.persisted,
                order=current.persisted.order.transition_to(OrderState.APPROVED),
            ),
        )
    else:
        store.on_lock = lambda current: setattr(current, "latest_audit_id", UUID(int=605))

    with pytest.raises(ReviewPreconditionFailedError):
        _invoke(monkeypatch, store, "approve", operator=APPROVER)

    assert not store.audit_events
    assert store.persisted.order.state in (OrderState.APPROVED, OrderState.READY_FOR_APPROVAL)


def test_missing_order_is_safe_and_leaves_preflight_transaction_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    store.install(monkeypatch)
    async_get = commands.get_order

    async def missing(session: FakeSession, order_id: UUID) -> None:
        await async_get(session, UUID(int=999))
        return None

    monkeypatch.setattr(commands, "get_order", missing)
    session = FakeSession(store)

    with pytest.raises(OrderNotFoundError):
        asyncio.run(commands.approve_order(session, ORDER_ID, '"' + "0" * 64 + '"', APPROVER, NOW))

    assert session.rollback_count == 1
    assert session.in_transaction() is False
    assert session.commit_count == 0


def test_final_audit_failure_rolls_back_state_and_audit_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(OrderState.FAILED_RETRYABLE, failure_origin=OrderState.SYNCING)
    store.fail_event_type = "ORDER_RETRY_RESTORED"
    session = FakeSession(store)
    store.install(monkeypatch)
    original_order = store.persisted.order

    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        asyncio.run(commands.retry_order(session, ORDER_ID, _etag(store), REVIEWER, NOW))

    assert store.persisted.order == original_order
    assert store.audit_events == []
    assert store.latest_audit_id == INITIAL_AUDIT_ID
    assert session.commit_count == 0
    assert session.write_rollback_count == 1
    assert session.in_transaction() is False


def test_timezone_aware_recorded_at_is_required_before_any_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    store.install(monkeypatch)
    session = FakeSession(store)

    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(
            commands.approve_order(
                session,
                ORDER_ID,
                _etag(store),
                APPROVER,
                datetime(2030, 1, 2),
            )
        )

    assert store.order_reads == 0
    assert not store.audit_events
