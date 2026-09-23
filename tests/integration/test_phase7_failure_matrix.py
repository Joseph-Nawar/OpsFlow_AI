"""PostgreSQL proof for Task 7 failure classification and persistence."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

import opsflow.orchestration.failures as failures_module
from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
)
from opsflow.documents.errors import DocumentParseError
from opsflow.domain import (
    AuditEvent,
    InvalidStateTransitionError,
    Order,
    OrderState,
    SourceDocument,
    SourceDocumentType,
)
from opsflow.extraction.errors import ProviderError, ProviderUnavailableError
from opsflow.orchestration.failures import (
    FailureClassification,
    classify_extracted_failure,
    classify_processing_failure,
    persist_orchestration_failure,
)
from opsflow.persistence.repositories import (
    get_audit_events,
    get_order,
    insert_order_graph,
)
from opsflow.settings import Settings

RECORDED_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
PROCESSING_DESCRIPTION = "Orchestration processing stopped with a persisted operational failure."
EXTRACTED_DESCRIPTION = (
    "Deterministic validation could not complete; a persisted operational failure was recorded."
)


def _source(source_id: UUID) -> SourceDocument:
    return SourceDocument(
        id=source_id,
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256=uuid4().hex * 2,
        message_id="synthetic-message",
        storage_reference="synthetic://purchase-order.pdf",
        metadata=(),
    )


def _order(state: OrderState) -> tuple[Order, UUID]:
    order_id, source_id = uuid4(), uuid4()
    source = _source(source_id)
    if state is OrderState.PROCESSING:
        order = Order.received(
            order_id,
            source_documents=(source,),
        ).transition_to(state)
    else:
        order = Order(
            id=order_id,
            source_documents=(source,),
            state=state,
        )
    return order, source_id


async def _commit_order(engine: AsyncEngine, order: Order) -> None:
    async with AsyncSession(engine) as session:
        await insert_order_graph(session, order, RECORDED_AT)
        await session.commit()


def _engine() -> AsyncEngine:
    return create_async_engine(Settings().database_url)


def test_processing_retryable_failure_persists_origin_and_audit() -> None:
    asyncio.run(_assert_processing_retryable_failure())


async def _assert_processing_retryable_failure() -> None:
    order, _ = _order(OrderState.PROCESSING)
    engine = _engine()
    try:
        await _commit_order(engine, order)
        classification = classify_processing_failure(
            ProviderUnavailableError("SYNTHETIC-PROVIDER-DIAGNOSTIC")
        )
        async with AsyncSession(engine) as session:
            persisted = await persist_orchestration_failure(
                session,
                order_id=order.id,
                classification=classification,
                actor="orchestration:n8n",
                recorded_at=RECORDED_AT,
            )
            assert session.in_transaction() is False

        assert persisted.order.state is OrderState.FAILED_RETRYABLE
        assert persisted.order.failure_origin is OrderState.PROCESSING
        async with AsyncSession(engine) as session:
            audits = await get_audit_events(session, order.id)
        assert len(audits) == 1
        assert audits[0] == AuditEvent(
            id=audits[0].id,
            order_id=order.id,
            event_type="ORDER_PROCESSING_FAILED",
            actor="orchestration:n8n",
            occurred_at=RECORDED_AT,
            description=PROCESSING_DESCRIPTION,
        )
    finally:
        await engine.dispose()


def test_processing_final_failure_persists_failed_final() -> None:
    asyncio.run(_assert_processing_final_failure())


async def _assert_processing_final_failure() -> None:
    order, _ = _order(OrderState.PROCESSING)
    engine = _engine()
    try:
        await _commit_order(engine, order)
        classification = classify_processing_failure(
            DocumentParseError("SYNTHETIC-DOCUMENT-DIAGNOSTIC")
        )
        async with AsyncSession(engine) as session:
            persisted = await persist_orchestration_failure(
                session,
                order_id=order.id,
                classification=classification,
                actor="orchestration:n8n",
                recorded_at=RECORDED_AT,
            )
        assert persisted.order.state is OrderState.FAILED_FINAL
        assert persisted.order.failure_origin is OrderState.PROCESSING
        async with AsyncSession(engine) as session:
            audits = await get_audit_events(session, order.id)
        assert [event.event_type for event in audits] == ["ORDER_PROCESSING_FAILED"]
        assert audits[0].description == PROCESSING_DESCRIPTION
    finally:
        await engine.dispose()


def test_extracted_retryable_failure_persists_origin_and_audit() -> None:
    asyncio.run(_assert_extracted_retryable_failure())


async def _assert_extracted_retryable_failure() -> None:
    order, _ = _order(OrderState.EXTRACTED)
    engine = _engine()
    try:
        await _commit_order(engine, order)
        classification = classify_extracted_failure(BusinessDataProviderError())
        async with AsyncSession(engine) as session:
            persisted = await persist_orchestration_failure(
                session,
                order_id=order.id,
                classification=classification,
                actor="orchestration:n8n",
                recorded_at=RECORDED_AT,
            )
            assert session.in_transaction() is False
        assert persisted.order.state is OrderState.FAILED_RETRYABLE
        assert persisted.order.failure_origin is OrderState.EXTRACTED
        async with AsyncSession(engine) as session:
            audits = await get_audit_events(session, order.id)
        assert [event.event_type for event in audits] == ["ORDER_VALIDATION_FAILED"]
        assert audits[0].description == EXTRACTED_DESCRIPTION
    finally:
        await engine.dispose()


def test_extracted_final_failure_persists_failed_final() -> None:
    asyncio.run(_assert_extracted_final_failure())


async def _assert_extracted_final_failure() -> None:
    order, _ = _order(OrderState.EXTRACTED)
    engine = _engine()
    try:
        await _commit_order(engine, order)
        classification = classify_extracted_failure(InvalidTrustedDataError())
        async with AsyncSession(engine) as session:
            persisted = await persist_orchestration_failure(
                session,
                order_id=order.id,
                classification=classification,
                actor="orchestration:n8n",
                recorded_at=RECORDED_AT,
            )
        assert persisted.order.state is OrderState.FAILED_FINAL
        assert persisted.order.failure_origin is OrderState.EXTRACTED
        async with AsyncSession(engine) as session:
            audits = await get_audit_events(session, order.id)
        assert [event.event_type for event in audits] == ["ORDER_VALIDATION_FAILED"]
        assert audits[0].description == EXTRACTED_DESCRIPTION
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("current_state", "classification"),
    [
        (
            OrderState.EXTRACTED,
            classify_processing_failure(ProviderError("stale-processing")),
        ),
        (
            OrderState.PROCESSING,
            classify_extracted_failure(BusinessDataProviderError()),
        ),
    ],
)
def test_stale_origin_failure_is_rejected_without_audit(
    current_state: OrderState,
    classification: FailureClassification,
) -> None:
    asyncio.run(_assert_stale_origin(current_state, classification))


async def _assert_stale_origin(
    current_state: OrderState,
    classification: FailureClassification,
) -> None:
    order, _ = _order(current_state)
    engine = _engine()
    try:
        await _commit_order(engine, order)
        async with AsyncSession(engine) as session:
            with pytest.raises(InvalidStateTransitionError):
                await persist_orchestration_failure(
                    session,
                    order_id=order.id,
                    classification=classification,
                    actor="orchestration:n8n",
                    recorded_at=RECORDED_AT,
                )
            assert session.in_transaction() is False
        async with AsyncSession(engine) as session:
            persisted = await get_order(session, order.id)
            audits = await get_audit_events(session, order.id)
        assert persisted is not None
        assert persisted.order.state is current_state
        assert persisted.order.failure_origin is None
        assert audits == ()
    finally:
        await engine.dispose()


def test_audit_failure_rolls_back_state_and_propagates_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_audit_failure_rollback(monkeypatch))


async def _assert_audit_failure_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    order, _ = _order(OrderState.PROCESSING)
    engine = _engine()
    original_insert = failures_module.insert_audit_event

    async def fail_after_insert(*args: object, **kwargs: object) -> None:
        await original_insert(*args, **kwargs)
        raise SQLAlchemyError("SYNTHETIC-AUDIT-PERSISTENCE-DIAGNOSTIC")

    monkeypatch.setattr(failures_module, "insert_audit_event", fail_after_insert)
    try:
        await _commit_order(engine, order)
        classification = classify_processing_failure(ProviderError("final"))
        async with AsyncSession(engine) as session:
            with pytest.raises(SQLAlchemyError):
                await persist_orchestration_failure(
                    session,
                    order_id=order.id,
                    classification=classification,
                    actor="orchestration:n8n",
                    recorded_at=RECORDED_AT,
                )
            assert session.in_transaction() is False
        await _assert_original_state_and_no_audit(engine, order.id, OrderState.PROCESSING)
    finally:
        await engine.dispose()


def test_state_failure_rolls_back_without_audit_and_propagates_sqlalchemy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_state_failure_rollback(monkeypatch))


async def _assert_state_failure_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    order, _ = _order(OrderState.EXTRACTED)
    engine = _engine()
    original_update = failures_module.update_order_snapshot

    async def fail_after_update(*args: object, **kwargs: object) -> None:
        await original_update(*args, **kwargs)
        raise SQLAlchemyError("SYNTHETIC-STATE-PERSISTENCE-DIAGNOSTIC")

    monkeypatch.setattr(failures_module, "update_order_snapshot", fail_after_update)
    try:
        await _commit_order(engine, order)
        classification = classify_extracted_failure(InvalidTrustedDataError())
        async with AsyncSession(engine) as session:
            with pytest.raises(SQLAlchemyError):
                await persist_orchestration_failure(
                    session,
                    order_id=order.id,
                    classification=classification,
                    actor="orchestration:n8n",
                    recorded_at=RECORDED_AT,
                )
            assert session.in_transaction() is False
        await _assert_original_state_and_no_audit(engine, order.id, OrderState.EXTRACTED)
    finally:
        await engine.dispose()


async def _assert_original_state_and_no_audit(
    engine: AsyncEngine,
    order_id: UUID,
    state: OrderState,
) -> None:
    async with AsyncSession(engine) as session:
        persisted = await get_order(session, order_id)
        audits = await get_audit_events(session, order_id)
    assert persisted is not None
    assert persisted.order.state is state
    assert persisted.order.failure_origin is None
    assert audits == ()
