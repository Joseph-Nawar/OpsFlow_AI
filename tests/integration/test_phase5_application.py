"""PostgreSQL-backed tests for the internal Phase 5 validation operation."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

import opsflow.application.validation as validation_module
from opsflow.application.errors import OrderValidationStateError, ValidationFactsChangedError
from opsflow.application.validation import validate_order
from opsflow.domain import Order, OrderLine, OrderState, SourceDocument, SourceDocumentType
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.persistence.mappers import PersistedExtractionSnapshot
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_audit_events,
    get_extraction_snapshot,
    get_order,
    insert_extraction_snapshot,
    insert_order_graph,
)
from opsflow.settings import Settings
from opsflow.validation import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
    ValidationContext,
    ValidationFacts,
    ValidationRoute,
)
from opsflow.validation.policy import ValidationPolicy

RECORDED_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


class FixedProvider:
    def __init__(self, data: TrustedBusinessData) -> None:
        self.data = data
        self.calls = 0

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        self.calls += 1
        return self.data


def make_source(source_id: UUID, source_sha256: str | None = None) -> SourceDocument:
    effective_sha256 = uuid4().hex * 2 if source_sha256 is None else source_sha256
    return SourceDocument(
        id=source_id,
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256=effective_sha256,
        message_id=None,
        storage_reference="synthetic://purchase-order.pdf",
        metadata=(),
    )


def make_extracted_order(order_id: UUID, source: SourceDocument) -> Order:
    return Order(
        id=order_id,
        customer_reference="OLD-CUSTOMER",
        po_number="OLD-PO",
        order_date=date(2029, 1, 1),
        requested_delivery_date=date(2029, 1, 10),
        currency="USD",
        lines=(
            OrderLine(
                id=uuid4(),
                sku="OLD-SKU",
                description="old trusted line",
                quantity=Decimal("1"),
                submitted_price=Decimal("1"),
                trusted_catalogue_price=Decimal("1"),
            ),
        ),
        source_documents=(source,),
        state=OrderState.EXTRACTED,
    )


def make_draft(
    source: SourceDocument,
    *,
    quantity: Decimal | None = Decimal("2"),
    submitted_price: Decimal | None = Decimal("12"),
    currency: str | None = "USD",
    order_date: date | None = date(2030, 1, 1),
    delivery_date: date | None = date(2030, 1, 10),
    po_number: str | None = None,
) -> ExtractionDraft:
    effective_po_number = f"PO-{source.id.hex}" if po_number is None else po_number
    return ExtractionDraft(
        source_sha256=source.sha256,
        source_document_type=source.document_type,
        customer_name="Acme Ltd",
        customer_reference="CUST-1",
        po_number=effective_po_number,
        order_date=order_date,
        requested_delivery_date=delivery_date,
        currency=currency,
        lines=(
            ExtractedLine(
                sku="SKU-1",
                description="Widget",
                quantity=quantity,
                submitted_price=submitted_price,
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


def make_policy(high_value_threshold: str = "100") -> ValidationPolicy:
    return ValidationPolicy(
        supported_currencies=("USD",),
        price_tolerance_fraction=Decimal("0"),
        high_value_threshold=Decimal(high_value_threshold),
    )


def test_ready_validation_promotes_trusted_graph_and_audits_atomically() -> None:
    asyncio.run(_assert_ready_validation())


def test_uppercase_persisted_source_sha_matches_canonical_draft() -> None:
    asyncio.run(_assert_uppercase_persisted_source_sha())


def test_review_validation_preserves_trusted_graph_and_stores_untrusted_snapshot() -> None:
    asyncio.run(_assert_review_validation())


def test_high_value_ready_validation_is_elevated_without_new_order_state() -> None:
    asyncio.run(_assert_high_value_validation())


def test_duplicate_customer_po_from_another_order_becomes_local_validation_fact() -> None:
    asyncio.run(_assert_duplicate_customer_po_validation())


def test_duplicate_source_sha_from_another_order_becomes_local_validation_fact() -> None:
    asyncio.run(_assert_duplicate_sha_validation())


def test_final_write_failure_rolls_back_snapshot_graph_state_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_final_write_rollback(monkeypatch))


def test_final_state_race_aborts_without_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_assert_final_state_race(monkeypatch))


def test_final_validation_facts_change_aborts_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_final_facts_change(monkeypatch))


async def _assert_ready_validation() -> None:
    order_id, source_id = uuid4(), uuid4()
    source = make_source(source_id)
    order = make_extracted_order(order_id, source)
    engine = create_async_engine(Settings().database_url)
    try:
        await _commit_order(engine, order)
        provider = FixedProvider(make_business_data())
        async with AsyncSession(engine) as session:
            result = await validate_order(
                session,
                order_id,
                source_id,
                make_draft(source),
                provider,
                make_policy(),
                ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        assert provider.calls == 1
        assert result.order.state is OrderState.READY_FOR_APPROVAL
        assert result.validation_result.route is ValidationRoute.READY_FOR_APPROVAL
        assert result.order.customer_reference == "CUST-1"
        assert result.order.lines[0].sku == "SKU-1"
        assert result.order.lines[0].trusted_catalogue_price == Decimal("12")

        async with AsyncSession(engine) as session:
            persisted = await get_order(session, order_id)
            snapshot = await get_extraction_snapshot(session, order_id, source_id)
            audits = await get_audit_events(session, order_id)
        assert persisted is not None
        assert persisted.order == result.order
        assert snapshot is not None
        assert len(persisted.validation_issues) == 0
        assert [event.event_type for event in audits] == [
            "EXTRACTION_SNAPSHOT_RECORDED",
            "ORDER_VALIDATED",
            "ORDER_READY_FOR_APPROVAL",
        ]
        assert [event.actor for event in audits] == ["system"] * 3
        assert [event.description for event in audits] == [
            "Immutable extraction snapshot recorded for the order source document.",
            "Deterministic validation completed.",
            "Deterministic validation passed; order is ready for approval.",
        ]
    finally:
        await engine.dispose()


async def _assert_uppercase_persisted_source_sha() -> None:
    order_id, source_id = uuid4(), uuid4()
    canonical_source = make_source(source_id, "a" * 64)
    persisted_source = make_source(source_id, "A" * 64)
    order = make_extracted_order(order_id, persisted_source)
    engine = create_async_engine(Settings().database_url)
    try:
        await _commit_order(engine, order)
        async with AsyncSession(engine) as session:
            result = await validate_order(
                session,
                order_id,
                source_id,
                make_draft(canonical_source),
                FixedProvider(make_business_data()),
                make_policy(),
                ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )

        assert result.validation_result.route is ValidationRoute.READY_FOR_APPROVAL
        async with AsyncSession(engine) as session:
            snapshot = await get_extraction_snapshot(session, order_id, source_id)
            persisted = await get_order(session, order_id)
        assert snapshot is not None
        assert snapshot.source_sha256 == "a" * 64
        assert snapshot.draft.source_sha256 == "a" * 64
        assert persisted is not None
        assert persisted.order.source_documents[0].sha256 == "A" * 64
    finally:
        await engine.dispose()


async def _assert_review_validation() -> None:
    order_id, source_id = uuid4(), uuid4()
    source = make_source(source_id)
    order = make_extracted_order(order_id, source)
    draft = make_draft(
        source,
        quantity=None,
        submitted_price=None,
        currency="EUR",
        order_date=date(2031, 1, 1),
        delivery_date=date(2030, 1, 1),
    )
    engine = create_async_engine(Settings().database_url)
    try:
        await _commit_order(engine, order)
        async with AsyncSession(engine) as session:
            result = await validate_order(
                session,
                order_id,
                source_id,
                draft,
                FixedProvider(make_business_data()),
                make_policy(),
                ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        assert result.order.state is OrderState.NEEDS_REVIEW
        assert result.validation_result.route is ValidationRoute.NEEDS_REVIEW
        assert result.order.customer_reference == order.customer_reference
        assert result.order.lines == order.lines

        async with AsyncSession(engine) as session:
            persisted = await get_order(session, order_id)
            snapshot = await get_extraction_snapshot(session, order_id, source_id)
            audits = await get_audit_events(session, order_id)
        assert persisted is not None
        assert persisted.order.customer_reference == order.customer_reference
        assert persisted.order.lines == order.lines
        assert snapshot is not None
        assert snapshot.draft.lines[0].quantity is None
        assert snapshot.draft.lines[0].submitted_price is None
        assert [issue.rule_code for issue in persisted.validation_issues] == [
            "ORDER_DATE_IN_FUTURE",
            "DELIVERY_DATE_IN_PAST",
            "DELIVERY_BEFORE_ORDER_DATE",
            "UNSUPPORTED_CURRENCY",
            "QUANTITY_REQUIRED",
            "SUBMITTED_PRICE_REQUIRED",
        ]
        assert persisted.validation_issues == result.validation_result.issues
        assert [event.event_type for event in audits] == [
            "EXTRACTION_SNAPSHOT_RECORDED",
            "ORDER_VALIDATED",
            "ORDER_NEEDS_REVIEW",
        ]
    finally:
        await engine.dispose()


async def _assert_high_value_validation() -> None:
    order_id, source_id = uuid4(), uuid4()
    source = make_source(source_id)
    order = make_extracted_order(order_id, source)
    engine = create_async_engine(Settings().database_url)
    try:
        await _commit_order(engine, order)
        async with AsyncSession(engine) as session:
            result = await validate_order(
                session,
                order_id,
                source_id,
                make_draft(source),
                FixedProvider(make_business_data()),
                make_policy("24"),
                ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        assert result.order.state is OrderState.READY_FOR_APPROVAL
        assert result.validation_result.approval_level.value == "ELEVATED"
        assert [issue.rule_code for issue in result.validation_result.issues] == [
            "HIGH_VALUE_APPROVAL_REQUIRED"
        ]
        async with AsyncSession(engine) as session:
            persisted = await get_order(session, order_id)
            audits = await get_audit_events(session, order_id)
        assert persisted is not None
        assert [issue.rule_code for issue in persisted.validation_issues] == [
            "HIGH_VALUE_APPROVAL_REQUIRED"
        ]
        assert audits[-1].description == (
            "Deterministic validation passed; elevated approval is required."
        )
    finally:
        await engine.dispose()


async def _assert_duplicate_customer_po_validation() -> None:
    first_order_id, first_source_id = uuid4(), uuid4()
    second_order_id, second_source_id = uuid4(), uuid4()
    duplicate_po = "DUPLICATE-PO"
    first_source = make_source(first_source_id)
    second_source = make_source(second_source_id)
    first_order = make_extracted_order(first_order_id, first_source)
    second_order = make_extracted_order(second_order_id, second_source)
    engine = create_async_engine(Settings().database_url)
    try:
        await _commit_order(engine, first_order)
        async with AsyncSession(engine) as session:
            first_result = await validate_order(
                session,
                first_order_id,
                first_source_id,
                make_draft(first_source, po_number=duplicate_po),
                FixedProvider(make_business_data()),
                make_policy(),
                ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        assert first_result.order.state is OrderState.READY_FOR_APPROVAL

        await _commit_order(engine, second_order)
        async with AsyncSession(engine) as session:
            result = await validate_order(
                session,
                second_order_id,
                second_source_id,
                make_draft(second_source, po_number=duplicate_po),
                FixedProvider(make_business_data()),
                make_policy(),
                ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )

        assert result.order.state is OrderState.NEEDS_REVIEW
        assert [issue.rule_code for issue in result.validation_result.issues] == [
            "DUPLICATE_CUSTOMER_PO"
        ]
        async with AsyncSession(engine) as session:
            persisted = await get_order(session, second_order_id)
        assert persisted is not None
        assert persisted.validation_issues == result.validation_result.issues
        assert persisted.order.customer_reference == second_order.customer_reference
        assert persisted.order.po_number == second_order.po_number
    finally:
        await engine.dispose()


async def _assert_duplicate_sha_validation() -> None:
    first_order_id, first_source_id = uuid4(), uuid4()
    second_order_id, second_source_id = uuid4(), uuid4()
    shared_sha256 = "f" * 64
    first_source = make_source(first_source_id, shared_sha256)
    second_source = make_source(second_source_id, shared_sha256)
    first_order = make_extracted_order(first_order_id, first_source)
    second_order = make_extracted_order(second_order_id, second_source)
    draft = make_draft(second_source)
    engine = create_async_engine(Settings().database_url)
    try:
        await _commit_order(engine, first_order)
        await _commit_order(engine, second_order)
        async with AsyncSession(engine) as session:
            await insert_extraction_snapshot(
                session,
                PersistedExtractionSnapshot(
                    id=uuid4(),
                    order_id=first_order_id,
                    source_document_id=first_source_id,
                    source_sha256=draft.source_sha256,
                    source_document_type=draft.source_document_type,
                    draft=make_draft(first_source),
                    created_at=RECORDED_AT,
                ),
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            result = await validate_order(
                session,
                second_order_id,
                second_source_id,
                draft,
                FixedProvider(make_business_data()),
                make_policy(),
                ValidationContext(date(2030, 1, 2)),
                RECORDED_AT,
            )
        assert result.validation_result.route is ValidationRoute.NEEDS_REVIEW
        assert any(
            issue.rule_code == "DOCUMENT_ALREADY_PROCESSED"
            for issue in result.validation_result.issues
        )
    finally:
        await engine.dispose()


async def _assert_final_write_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    order_id, source_id = uuid4(), uuid4()
    source = make_source(source_id)
    order = make_extracted_order(order_id, source)
    engine = create_async_engine(Settings().database_url)

    async def fail_graph(session: AsyncSession, order: Order) -> None:
        raise RuntimeError("controlled graph failure")

    monkeypatch.setattr(validation_module, "replace_order_graph", fail_graph)
    try:
        await _commit_order(engine, order)
        async with AsyncSession(engine) as session:
            with pytest.raises(RuntimeError, match="controlled graph failure"):
                await validate_order(
                    session,
                    order_id,
                    source_id,
                    make_draft(source),
                    FixedProvider(make_business_data()),
                    make_policy(),
                    ValidationContext(date(2030, 1, 2)),
                    RECORDED_AT,
                )

        async with AsyncSession(engine) as session:
            persisted = await get_order(session, order_id)
            snapshot = await get_extraction_snapshot(session, order_id, source_id)
            audits = await get_audit_events(session, order_id)
        assert persisted is not None
        assert persisted.order == order
        assert snapshot is None
        assert audits == ()
    finally:
        await engine.dispose()


async def _assert_final_state_race(monkeypatch: pytest.MonkeyPatch) -> None:
    order_id, source_id = uuid4(), uuid4()
    source = make_source(source_id)
    order = make_extracted_order(order_id, source)
    raced_order = order.transition_to(OrderState.VALIDATED).transition_to(
        OrderState.READY_FOR_APPROVAL
    )
    engine = create_async_engine(Settings().database_url)

    async def return_raced_order(session: AsyncSession, requested_order_id: UUID) -> PersistedOrder:
        return PersistedOrder(raced_order, RECORDED_AT, ())

    monkeypatch.setattr(validation_module, "get_order_for_update", return_raced_order)
    try:
        await _commit_order(engine, order)
        async with AsyncSession(engine) as session:
            with pytest.raises(OrderValidationStateError):
                await validate_order(
                    session,
                    order_id,
                    source_id,
                    make_draft(source),
                    FixedProvider(make_business_data()),
                    make_policy(),
                    ValidationContext(date(2030, 1, 2)),
                    RECORDED_AT,
                )

        async with AsyncSession(engine) as session:
            persisted = await get_order(session, order_id)
            snapshot = await get_extraction_snapshot(session, order_id, source_id)
            audits = await get_audit_events(session, order_id)
        assert persisted is not None
        assert persisted.order == order
        assert snapshot is None
        assert audits == ()
    finally:
        await engine.dispose()


async def _assert_final_facts_change(monkeypatch: pytest.MonkeyPatch) -> None:
    order_id, source_id = uuid4(), uuid4()
    source = make_source(source_id)
    order = make_extracted_order(order_id, source)
    engine = create_async_engine(Settings().database_url)
    original_build_facts = validation_module.build_validation_facts
    calls = 0

    async def changed_facts(session: AsyncSession, **kwargs: object) -> ValidationFacts:
        nonlocal calls
        calls += 1
        facts = await original_build_facts(session, **kwargs)
        return facts if calls == 1 else ValidationFacts(True, facts.document_already_processed)

    monkeypatch.setattr(validation_module, "build_validation_facts", changed_facts)
    try:
        await _commit_order(engine, order)
        async with AsyncSession(engine) as session:
            with pytest.raises(ValidationFactsChangedError):
                await validate_order(
                    session,
                    order_id,
                    source_id,
                    make_draft(source),
                    FixedProvider(make_business_data()),
                    make_policy(),
                    ValidationContext(date(2030, 1, 2)),
                    RECORDED_AT,
                )

        async with AsyncSession(engine) as session:
            persisted = await get_order(session, order_id)
            snapshot = await get_extraction_snapshot(session, order_id, source_id)
            audits = await get_audit_events(session, order_id)
        assert calls == 2
        assert persisted is not None
        assert persisted.order == order
        assert snapshot is None
        assert audits == ()
    finally:
        await engine.dispose()


async def _commit_order(engine: AsyncEngine, order: Order) -> None:
    async with AsyncSession(engine) as session:
        await insert_order_graph(session, order, RECORDED_AT)
        await session.commit()
