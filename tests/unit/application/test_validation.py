"""Unit tests for the Phase 5 internal validation operation."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

import opsflow.application.validation as validation_module
from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
    OrderNotFoundError,
    SnapshotConflictError,
    SnapshotReplayError,
    SourceOwnershipError,
)
from opsflow.domain import Order, OrderLine, OrderState, SourceDocument, SourceDocumentType
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.persistence.mappers import PersistedExtractionSnapshot
from opsflow.persistence.repositories import PersistedOrder
from opsflow.validation import (
    ApprovalLevel,
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
    ValidatedOrderData,
    ValidatedOrderLine,
    ValidationFacts,
    ValidationResult,
    ValidationRoute,
)
from opsflow.validation.business_data import TrustedBusinessDataContractError

ORDER_ID = UUID(int=1)
SOURCE_ID = UUID(int=2)
LINE_ID = UUID(int=3)
RECORDED_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


class FakeSession:
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


def make_source() -> SourceDocument:
    return SourceDocument(
        id=SOURCE_ID,
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        message_id=None,
        storage_reference="synthetic://purchase-order.pdf",
        metadata=(),
    )


def make_order(state: OrderState = OrderState.EXTRACTED) -> Order:
    return Order(
        id=ORDER_ID,
        customer_reference="OLD-CUSTOMER",
        po_number="OLD-PO",
        order_date=date(2029, 1, 1),
        requested_delivery_date=date(2029, 1, 10),
        currency="USD",
        lines=(
            OrderLine(
                id=LINE_ID,
                sku="OLD-SKU",
                description="old trusted line",
                quantity=Decimal("1"),
                submitted_price=Decimal("1"),
                trusted_catalogue_price=Decimal("1"),
            ),
        ),
        source_documents=(make_source(),),
        state=state,
    )


def make_draft() -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme Ltd",
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 1, 10),
        currency="USD",
        lines=(
            ExtractedLine(
                sku="SKU-1",
                description="Widget",
                quantity=Decimal("2"),
                submitted_price=Decimal("10"),
            ),
        ),
        notes=None,
        evidence=(),
    )


def make_business_data() -> TrustedBusinessData:
    return TrustedBusinessData(
        customer_candidates=(TrustedCustomer("CUST-1", "Acme Ltd", True),),
        products_by_line=(
            TrustedProduct(
                sku="SKU-1",
                description="Trusted widget",
                active=True,
                currency="USD",
                catalogue_price=Decimal("12"),
                available_quantity=Decimal("5"),
            ),
        ),
    )


def make_validated_data() -> ValidatedOrderData:
    return ValidatedOrderData(
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 1, 10),
        currency="USD",
        lines=(
            ValidatedOrderLine(
                sku="SKU-1",
                description="Trusted widget",
                quantity=Decimal("2"),
                submitted_price=Decimal("10"),
                trusted_catalogue_price=Decimal("12"),
            ),
        ),
    )


def make_result(route: ValidationRoute = ValidationRoute.READY_FOR_APPROVAL) -> ValidationResult:
    return ValidationResult(
        issues=(),
        route=route,
        approval_level=ApprovalLevel.STANDARD,
        order_total=Decimal("20"),
        validated_order_data=make_validated_data()
        if route is ValidationRoute.READY_FOR_APPROVAL
        else None,
    )


def make_persisted_order(state: OrderState = OrderState.EXTRACTED) -> PersistedOrder:
    return PersistedOrder(
        order=make_order(state),
        created_at=RECORDED_AT,
        validation_issues=(),
    )


def make_snapshot(draft: ExtractionDraft) -> PersistedExtractionSnapshot:
    return PersistedExtractionSnapshot(
        id=UUID(int=10),
        order_id=ORDER_ID,
        source_document_id=SOURCE_ID,
        source_sha256=draft.source_sha256,
        source_document_type=draft.source_document_type,
        draft=draft,
        created_at=RECORDED_AT,
    )


class RecordingProvider:
    def __init__(self, session: FakeSession, result: TrustedBusinessData) -> None:
        self.session = session
        self.result = result
        self.calls: list[BusinessDataLookupRequest] = []

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        assert not self.session.in_transaction()
        self.calls.append(request)
        return self.result


def install_repository_doubles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    persisted: PersistedOrder | None = None,
    existing_snapshot: PersistedExtractionSnapshot | None = None,
    facts: ValidationFacts | None = None,
) -> dict[str, list[object]]:
    facts = ValidationFacts(False, False) if facts is None else facts
    calls: dict[str, list[object]] = {
        "facts": [],
        "snapshots": [],
        "issues": [],
        "orders": [],
        "audits": [],
    }
    current = make_persisted_order() if persisted is None else persisted

    async def get_order(session: FakeSession, order_id: UUID) -> PersistedOrder | None:
        return current

    async def source_owner(session: FakeSession, source_document_id: UUID) -> UUID | None:
        return None

    async def get_snapshot(
        session: FakeSession, order_id: UUID, source_document_id: UUID
    ) -> PersistedExtractionSnapshot | None:
        calls["snapshots"].append((order_id, source_document_id))
        return existing_snapshot

    async def build_facts(session: FakeSession, **kwargs: object) -> ValidationFacts:
        calls["facts"].append((session.in_transaction(), kwargs))
        return facts

    async def get_for_update(session: FakeSession, order_id: UUID) -> PersistedOrder | None:
        return current

    async def insert_snapshot(session: FakeSession, snapshot: PersistedExtractionSnapshot) -> None:
        calls["snapshots"].append(snapshot)

    async def replace_issues(
        session: FakeSession, order_id: UUID, issues: tuple[object, ...]
    ) -> None:
        calls["issues"].append((order_id, issues))

    async def update_order(session: FakeSession, order: Order) -> None:
        calls["orders"].append(order)

    async def replace_graph(session: FakeSession, order: Order) -> None:
        calls["orders"].append(order)

    async def insert_audit(session: FakeSession, event: object) -> None:
        calls["audits"].append(event)

    for name, function in {
        "get_order": get_order,
        "get_source_document_order_id": source_owner,
        "get_extraction_snapshot": get_snapshot,
        "build_validation_facts": build_facts,
        "get_order_for_update": get_for_update,
        "insert_extraction_snapshot": insert_snapshot,
        "replace_validation_issues": replace_issues,
        "update_order_snapshot": update_order,
        "replace_order_graph": replace_graph,
        "insert_audit_event": insert_audit,
    }.items():
        monkeypatch.setattr(validation_module, name, function)
    return calls


def test_validate_order_builds_reference_request_and_closes_read_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    provider = RecordingProvider(session, make_business_data())
    calls = install_repository_doubles(monkeypatch)
    engine_calls: list[tuple[object, ...]] = []

    def validate(*args: object) -> ValidationResult:
        assert not session.in_transaction()
        engine_calls.append(args)
        return make_result()

    monkeypatch.setattr(validation_module.validation_engine, "validate", validate)

    result = asyncio.run(
        validation_module.validate_order(
            session,
            ORDER_ID,
            SOURCE_ID,
            make_draft(),
            provider,
            validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
            validation_module.ValidationContext(date(2030, 1, 2)),
            RECORDED_AT,
        )
    )

    assert provider.calls == [
        BusinessDataLookupRequest(customer_reference="CUST-1", customer_name=None, skus=("SKU-1",))
    ]
    assert len(engine_calls) == 1
    assert len(calls["facts"]) == 2
    assert calls["facts"][0][0] is False
    assert calls["facts"][1][0] is True
    assert session.rollback_count == 2
    assert session.commit_count == 1
    assert result.order.state is OrderState.READY_FOR_APPROVAL


def test_validate_order_distinguishes_missing_order_and_source_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    provider = RecordingProvider(session, make_business_data())
    install_repository_doubles(monkeypatch, persisted=None)
    monkeypatch.setattr(
        validation_module,
        "get_order",
        lambda session, order_id: _async_none(),
    )

    with pytest.raises(OrderNotFoundError):
        asyncio.run(
            validation_module.validate_order(
                session,
                ORDER_ID,
                SOURCE_ID,
                make_draft(),
                provider,
                validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                validation_module.ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        )
    assert provider.calls == []

    session = FakeSession()
    install_repository_doubles(monkeypatch)

    async def other_owner(session: FakeSession, source_document_id: UUID) -> UUID:
        return UUID(int=99)

    monkeypatch.setattr(validation_module, "get_source_document_order_id", other_owner)
    monkeypatch.setattr(validation_module, "get_order", _async_current_order)

    with pytest.raises(SourceOwnershipError):
        asyncio.run(
            validation_module.validate_order(
                session,
                ORDER_ID,
                UUID(int=99),
                make_draft(),
                provider,
                validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                validation_module.ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        )


def test_validate_order_classifies_replay_and_conflict_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = make_draft()
    provider = RecordingProvider(FakeSession(), make_business_data())
    conflict_draft = ExtractionDraft(
        source_sha256=draft.source_sha256,
        source_document_type=draft.source_document_type,
        customer_name=draft.customer_name,
        customer_reference=draft.customer_reference,
        po_number="PO-OTHER",
        order_date=draft.order_date,
        requested_delivery_date=draft.requested_delivery_date,
        currency=draft.currency,
        lines=draft.lines,
        notes=draft.notes,
        evidence=draft.evidence,
    )
    for existing, current_draft, expected in (
        (make_snapshot(draft), draft, SnapshotReplayError),
        (make_snapshot(draft), conflict_draft, SnapshotConflictError),
    ):
        session = FakeSession()
        install_repository_doubles(monkeypatch, existing_snapshot=existing)
        with pytest.raises(expected):
            asyncio.run(
                validation_module.validate_order(
                    session,
                    ORDER_ID,
                    SOURCE_ID,
                    current_draft,
                    provider,
                    validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                    validation_module.ValidationContext(date(2030, 1, 2)),
                    RECORDED_AT,
                )
            )
    assert provider.calls == []


def test_validate_order_translates_provider_contract_and_operational_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_repository_doubles(monkeypatch)

    class ContractProvider(RecordingProvider):
        async def get_validation_data(
            self, request: BusinessDataLookupRequest
        ) -> TrustedBusinessData:
            assert not self.session.in_transaction()
            raise TrustedBusinessDataContractError("malformed provider payload")

    session = FakeSession()
    with pytest.raises(InvalidTrustedDataError, match="Trusted business data failed"):
        asyncio.run(
            validation_module.validate_order(
                session,
                ORDER_ID,
                SOURCE_ID,
                make_draft(),
                ContractProvider(session, make_business_data()),
                validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                validation_module.ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        )

    class OperationalProvider(RecordingProvider):
        async def get_validation_data(
            self, request: BusinessDataLookupRequest
        ) -> TrustedBusinessData:
            assert not self.session.in_transaction()
            raise RuntimeError("provider secret")

    session = FakeSession()
    with pytest.raises(BusinessDataProviderError, match="Business data provider operation"):
        asyncio.run(
            validation_module.validate_order(
                session,
                ORDER_ID,
                SOURCE_ID,
                make_draft(),
                OperationalProvider(session, make_business_data()),
                validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                validation_module.ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        )


def test_validate_order_aborts_on_changed_facts_without_rerunning_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    provider = RecordingProvider(session, make_business_data())
    calls = install_repository_doubles(monkeypatch)
    fact_values = iter((ValidationFacts(False, False), ValidationFacts(True, False)))
    fact_calls: list[bool] = []

    async def changing_facts(session: FakeSession, **kwargs: object) -> ValidationFacts:
        fact_calls.append(session.in_transaction())
        return next(fact_values)

    monkeypatch.setattr(validation_module, "build_validation_facts", changing_facts)
    engine_calls: list[object] = []

    def validate(*args: object) -> ValidationResult:
        engine_calls.append(args)
        return make_result(ValidationRoute.NEEDS_REVIEW)

    monkeypatch.setattr(validation_module.validation_engine, "validate", validate)

    with pytest.raises(validation_module.ValidationFactsChangedError):
        asyncio.run(
            validation_module.validate_order(
                session,
                ORDER_ID,
                SOURCE_ID,
                make_draft(),
                provider,
                validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                validation_module.ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        )

    assert fact_calls == [False, True]
    assert len(engine_calls) == 1
    assert session.commit_count == 0
    assert session.write_rollback_count == 1
    assert not any(isinstance(item, PersistedExtractionSnapshot) for item in calls["snapshots"])


def test_validate_order_rejects_state_race_after_engine_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    provider = RecordingProvider(session, make_business_data())
    calls = install_repository_doubles(monkeypatch)
    monkeypatch.setattr(
        validation_module,
        "get_order_for_update",
        lambda session, order_id: _async_persisted_order(OrderState.READY_FOR_APPROVAL),
    )
    monkeypatch.setattr(
        validation_module.validation_engine,
        "validate",
        lambda *args: make_result(),
    )

    with pytest.raises(validation_module.OrderValidationStateError):
        asyncio.run(
            validation_module.validate_order(
                session,
                ORDER_ID,
                SOURCE_ID,
                make_draft(),
                provider,
                validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                validation_module.ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        )

    assert session.commit_count == 0
    assert session.write_rollback_count == 1
    assert not any(isinstance(item, PersistedExtractionSnapshot) for item in calls["snapshots"])


def test_validate_order_requires_aware_recorded_at() -> None:
    with pytest.raises(ValueError, match="recorded_at must be timezone-aware"):
        asyncio.run(
            validation_module.validate_order(
                FakeSession(),
                ORDER_ID,
                SOURCE_ID,
                make_draft(),
                RecordingProvider(FakeSession(), make_business_data()),
                validation_module.ValidationPolicy(("USD",), Decimal("0"), Decimal("100")),
                validation_module.ValidationContext(date(2030, 1, 2)),
                datetime(2030, 1, 2),
            )
        )


async def _async_none() -> None:
    return None


async def _async_current_order(session: FakeSession, order_id: UUID) -> PersistedOrder:
    return make_persisted_order()


async def _async_persisted_order(state: OrderState) -> PersistedOrder:
    return make_persisted_order(state)
