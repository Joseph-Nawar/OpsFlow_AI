"""PostgreSQL claim and retry-generation ownership proofs for Phase 7."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from opsflow.application.errors import IdempotencyConflictError, SourceIdentityMismatchError
from opsflow.application.orders import (
    CreateLineInput,
    CreateOrderInput,
    CreateSourceDocumentInput,
    create_order,
    fingerprint_order_request,
)
from opsflow.application.review_commands import retry_order
from opsflow.domain import AuditEvent, OrderState, SourceDocumentType
from opsflow.orchestration.auth import ORCHESTRATION_ACTOR
from opsflow.orchestration.claims import (
    IntakeClaim,
    IntakeClaimKind,
    OrchestrationSourceIdentity,
    claim_intake_execution,
)
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    ReviewRevisionModel,
    SourceDocumentModel,
    ValidationIssueModel,
)
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_audit_events,
    get_latest_audit_event_id,
    get_order_for_update,
    update_order_snapshot,
)
from opsflow.review import OperatorContext, OperatorRole
from opsflow.review.concurrency import compute_review_etag
from opsflow.settings import Settings

BASE_TIME = datetime(2030, 1, 1, tzinfo=UTC)
REVIEWER = OperatorContext(actor="reviewer:test", role=OperatorRole.REVIEWER)


def test_initial_claim_persists_processing_ownership() -> None:
    asyncio.run(_assert_initial_claim())


def test_ordinary_processing_duplicate_stands_down_without_writing() -> None:
    asyncio.run(_assert_ordinary_processing_duplicate())


def test_reviewer_restored_processing_resumes_once() -> None:
    asyncio.run(_assert_restored_processing())


def test_cross_origin_retry_history_resumes_latest_extracted_generation() -> None:
    asyncio.run(_assert_cross_origin_retry_history())


def test_concurrent_processing_redeliveries_consume_one_restore() -> None:
    asyncio.run(_assert_concurrent_processing_resume())


def test_restored_extracted_resumes_without_state_transition_and_is_consumed() -> None:
    asyncio.run(_assert_restored_extracted())


def test_source_identity_mismatches_do_not_consume_processing_restore() -> None:
    asyncio.run(_assert_source_identity_mismatches())


def test_idempotency_mismatches_do_not_consume_processing_restore() -> None:
    asyncio.run(_assert_idempotency_mismatches())


def test_multiple_source_documents_fail_closed_without_a_claim() -> None:
    asyncio.run(_assert_multiple_sources_fail_closed())


def test_restored_syncing_stands_down_without_phase7_resume() -> None:
    asyncio.run(_assert_restored_syncing())


async def _assert_initial_claim() -> None:
    engine = create_async_engine(Settings().database_url)
    persisted, request, key = await _create_order(engine)
    try:
        result = await _claim(
            engine, persisted, request, key, recorded_at=BASE_TIME + timedelta(minutes=2)
        )

        assert result.kind is IntakeClaimKind.INITIAL
        assert result.persisted.order.state is OrderState.PROCESSING
        assert result.source_document_id == persisted.order.source_documents[0].id
        events = await _events(engine, persisted.order.id)
        assert [event.event_type for event in events] == [
            "ORDER_RECEIVED",
            "ORDER_PROCESSING_STARTED",
        ]
        assert events[-1].actor == ORCHESTRATION_ACTOR
        assert events[-1].description == "Orchestration intake claimed the order for processing."
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _assert_ordinary_processing_duplicate() -> None:
    engine = create_async_engine(Settings().database_url)
    persisted, request, key = await _create_order(engine)
    try:
        await _claim(engine, persisted, request, key)
        before = await _events(engine, persisted.order.id)
        result = await _claim(engine, persisted, request, key)

        assert result.kind is IntakeClaimKind.STAND_DOWN
        assert result.persisted.order.state is OrderState.PROCESSING
        assert await _events(engine, persisted.order.id) == before
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _assert_restored_processing() -> None:
    engine = create_async_engine(Settings().database_url)
    persisted, request, key = await _create_order(engine)
    try:
        await _claim(engine, persisted, request, key)
        await _persist_failure(engine, persisted.order.id, OrderState.PROCESSING)
        await _reviewer_retry(engine, persisted.order.id)

        result = await _claim(
            engine,
            persisted,
            request,
            key,
            recorded_at=BASE_TIME + timedelta(minutes=2),
        )
        assert result.kind is IntakeClaimKind.RESUME_PROCESSING
        assert result.persisted.order.state is OrderState.PROCESSING
        events = await _events(engine, persisted.order.id)
        assert [event.event_type for event in events].count("ORDER_PROCESSING_RESUMED") == 1
        assert events[-1].actor == ORCHESTRATION_ACTOR
        assert (
            events[-1].description
            == "Human-authorized processing retry redelivery claimed for execution."
        )
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _assert_cross_origin_retry_history() -> None:
    engine = create_async_engine(Settings().database_url)
    persisted, request, key = await _create_order(engine)
    try:
        await _claim(engine, persisted, request, key)
        await _persist_failure(engine, persisted.order.id, OrderState.PROCESSING)
        await _reviewer_retry(engine, persisted.order.id)
        processing_resume = await _claim(
            engine,
            persisted,
            request,
            key,
            recorded_at=BASE_TIME + timedelta(minutes=2),
        )
        assert processing_resume.kind is IntakeClaimKind.RESUME_PROCESSING

        await _persist_failure(
            engine,
            persisted.order.id,
            OrderState.EXTRACTED,
            base_time=BASE_TIME + timedelta(minutes=3),
        )
        await _reviewer_retry(
            engine,
            persisted.order.id,
            recorded_at=BASE_TIME + timedelta(minutes=4),
        )
        extracted_resume = await _claim(
            engine,
            persisted,
            request,
            key,
            recorded_at=BASE_TIME + timedelta(minutes=5),
        )
        second_redelivery = await _claim(
            engine,
            persisted,
            request,
            key,
            recorded_at=BASE_TIME + timedelta(minutes=6),
        )

        assert extracted_resume.kind is IntakeClaimKind.RESUME_EXTRACTED
        assert second_redelivery.kind is IntakeClaimKind.STAND_DOWN
        assert extracted_resume.persisted.order.state is OrderState.EXTRACTED
        events = await _events(engine, persisted.order.id)
        assert [event.event_type for event in events].count("ORDER_PROCESSING_RESUMED") == 1
        assert [event.event_type for event in events].count("ORDER_EXTRACTION_RESUMED") == 1
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _assert_concurrent_processing_resume() -> None:
    engine = create_async_engine(Settings().database_url)
    persisted, request, key = await _create_order(engine)
    try:
        await _claim(engine, persisted, request, key)
        await _persist_failure(engine, persisted.order.id, OrderState.PROCESSING)
        await _reviewer_retry(engine, persisted.order.id)
        barrier = asyncio.Barrier(2)

        async def redelivery() -> IntakeClaim:
            await barrier.wait()
            return await _claim(
                engine,
                persisted,
                request,
                key,
                recorded_at=BASE_TIME + timedelta(minutes=2),
            )

        first, second = await asyncio.gather(redelivery(), redelivery())

        assert {first.kind, second.kind} == {
            IntakeClaimKind.RESUME_PROCESSING,
            IntakeClaimKind.STAND_DOWN,
        }
        events = await _events(engine, persisted.order.id)
        assert [event.event_type for event in events].count("ORDER_PROCESSING_RESUMED") == 1
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _assert_restored_extracted() -> None:
    engine = create_async_engine(Settings().database_url)
    persisted, request, key = await _create_order(engine)
    try:
        await _claim(engine, persisted, request, key)
        await _persist_failure(engine, persisted.order.id, OrderState.EXTRACTED)
        await _reviewer_retry(engine, persisted.order.id)

        first = await _claim(
            engine, persisted, request, key, recorded_at=BASE_TIME + timedelta(minutes=2)
        )
        second = await _claim(
            engine, persisted, request, key, recorded_at=BASE_TIME + timedelta(minutes=3)
        )

        assert first.kind is IntakeClaimKind.RESUME_EXTRACTED
        assert first.persisted.order.state is OrderState.EXTRACTED
        assert second.kind is IntakeClaimKind.STAND_DOWN
        events = await _events(engine, persisted.order.id)
        assert [event.event_type for event in events].count("ORDER_EXTRACTION_RESUMED") == 1
        assert (
            events[-1].description
            == "Human-authorized extraction retry redelivery claimed for execution."
        )
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _assert_source_identity_mismatches() -> None:
    mismatches = (
        replace(_source(), sha256="b" * 64),
        replace(_source(), document_type=SourceDocumentType.CSV),
        replace(_source(), name="different.pdf"),
        replace(_source(), mime_type="application/octet-stream"),
        replace(_source(), message_id="different-message"),
    )
    for mismatch in mismatches:
        engine = create_async_engine(Settings().database_url)
        persisted, request, key = await _create_order(engine)
        try:
            await _claim(engine, persisted, request, key)
            await _persist_failure(engine, persisted.order.id, OrderState.PROCESSING)
            await _reviewer_retry(engine, persisted.order.id)
            before = await _events(engine, persisted.order.id)

            with pytest.raises(SourceIdentityMismatchError):
                await _claim(engine, persisted, request, key, source=mismatch)

            assert await _events(engine, persisted.order.id) == before
            valid = await _claim(
                engine,
                persisted,
                request,
                key,
                recorded_at=BASE_TIME + timedelta(minutes=2),
            )
            assert valid.kind is IntakeClaimKind.RESUME_PROCESSING
        finally:
            await _delete_orders(engine, (persisted.order.id,))
            await engine.dispose()


async def _assert_idempotency_mismatches() -> None:
    engine = create_async_engine(Settings().database_url)
    first, request, key = await _create_order(engine)
    second, _, second_key = await _create_order(engine)
    different_request = replace(request, customer_reference="CUST-DIFFERENT")
    try:
        await _claim(engine, first, request, key)
        await _persist_failure(engine, first.order.id, OrderState.PROCESSING)
        await _reviewer_retry(engine, first.order.id)
        before = await _events(engine, first.order.id)

        cases = (
            ("missing-key", f"missing-{uuid4()}", fingerprint_order_request(request)),
            ("wrong-order", second_key, fingerprint_order_request(request)),
            ("wrong-fingerprint", key, fingerprint_order_request(different_request)),
        )
        for case, supplied_key, supplied_fingerprint in cases:
            try:
                await _claim(
                    engine,
                    first,
                    request,
                    supplied_key,
                    request_fingerprint=supplied_fingerprint,
                )
            except IdempotencyConflictError:
                pass
            else:
                pytest.fail(f"idempotency mismatch did not fail: {case}")
            assert await _events(engine, first.order.id) == before, case

        valid = await _claim(
            engine,
            first,
            request,
            key,
            recorded_at=BASE_TIME + timedelta(minutes=2),
        )
        assert valid.kind is IntakeClaimKind.RESUME_PROCESSING
    finally:
        await _delete_orders(engine, (first.order.id, second.order.id))
        await engine.dispose()


async def _assert_multiple_sources_fail_closed() -> None:
    engine = create_async_engine(Settings().database_url)
    request = _request(
        source_documents=(
            _source_input(message_id="message-1"),
            _source_input(name="second.pdf", message_id="message-2"),
        )
    )
    key = f"phase7-multiple-sources-{uuid4()}"
    persisted = await _create_order_with_request(engine, request, key)
    try:
        before = await _events(engine, persisted.order.id)
        with pytest.raises(SourceIdentityMismatchError):
            await _claim(engine, persisted, request, key, source=_source())
        assert await _events(engine, persisted.order.id) == before
        assert persisted.order.state is OrderState.RECEIVED
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _assert_restored_syncing() -> None:
    engine = create_async_engine(Settings().database_url)
    persisted, request, key = await _create_order(engine)
    try:
        await _claim(engine, persisted, request, key)
        await _persist_failure(engine, persisted.order.id, OrderState.SYNCING)
        await _reviewer_retry(engine, persisted.order.id)
        before = await _events(engine, persisted.order.id)

        result = await _claim(engine, persisted, request, key)

        assert result.kind is IntakeClaimKind.STAND_DOWN
        assert await _events(engine, persisted.order.id) == before
    finally:
        await _delete_orders(engine, (persisted.order.id,))
        await engine.dispose()


async def _create_order(engine: AsyncEngine) -> tuple[PersistedOrder, CreateOrderInput, str]:
    request = _request()
    key = f"phase7-claim-{uuid4()}"
    persisted = await _create_order_with_request(engine, request, key)
    return persisted, request, key


async def _create_order_with_request(
    engine: AsyncEngine,
    request: CreateOrderInput,
    key: str,
) -> PersistedOrder:
    async with AsyncSession(engine) as session:
        return await create_order(session, request, key, now=BASE_TIME - timedelta(minutes=1))


def _request(
    *,
    source_documents: tuple[CreateSourceDocumentInput, ...] | None = None,
) -> CreateOrderInput:
    return CreateOrderInput(
        customer_reference="CUST-PHASE7",
        po_number="PO-PHASE7",
        currency="USD",
        lines=(
            CreateLineInput(
                sku="SKU-PHASE7",
                description="Synthetic claim fixture",
                quantity=Decimal("1"),
                submitted_price=Decimal("10"),
                trusted_catalogue_price=Decimal("10"),
            ),
        ),
        source_documents=source_documents or (_source_input(),),
    )


def _source_input(
    *,
    name: str = "invoice.pdf",
    message_id: str | None = "message-1",
) -> CreateSourceDocumentInput:
    return CreateSourceDocumentInput(
        document_type=SourceDocumentType.PDF,
        name=name,
        mime_type="application/pdf",
        sha256="a" * 64,
        message_id=message_id,
    )


def _source() -> OrchestrationSourceIdentity:
    return OrchestrationSourceIdentity(
        document_type=SourceDocumentType.PDF,
        name="invoice.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        message_id="message-1",
    )


async def _claim(
    engine: AsyncEngine,
    persisted: PersistedOrder,
    request: CreateOrderInput,
    key: str,
    *,
    source: OrchestrationSourceIdentity | None = None,
    request_fingerprint: str | None = None,
    recorded_at: datetime = BASE_TIME,
) -> IntakeClaim:
    order_id = persisted.order.id
    async with AsyncSession(engine) as session:
        result = await claim_intake_execution(
            session,
            order_id=order_id,
            idempotency_key=key,
            request_fingerprint=request_fingerprint or fingerprint_order_request(request),
            source=source or _source(),
            actor=ORCHESTRATION_ACTOR,
            recorded_at=recorded_at,
        )
        assert not session.in_transaction()
        return result


async def _persist_failure(
    engine: AsyncEngine,
    order_id: UUID,
    origin: OrderState,
    *,
    base_time: datetime = BASE_TIME,
) -> None:
    async with AsyncSession(engine) as session, session.begin():
        persisted = await get_order_for_update(session, order_id)
        assert persisted is not None
        current = persisted.order
        events: list[AuditEvent] = []
        if origin is OrderState.PROCESSING:
            failed = current.transition_to(OrderState.FAILED_RETRYABLE)
            events.append(_audit(order_id, "ORDER_PROCESSING_FAILED", 10, base_time=base_time))
        elif origin is OrderState.EXTRACTED:
            extracted = current.transition_to(OrderState.EXTRACTED)
            failed = extracted.transition_to(OrderState.FAILED_RETRYABLE)
            events.extend(
                (
                    _audit(
                        order_id,
                        "ORDER_EXTRACTION_COMPLETED",
                        10,
                        base_time=base_time,
                    ),
                    _audit(order_id, "ORDER_VALIDATION_FAILED", 11, base_time=base_time),
                )
            )
        elif origin is OrderState.SYNCING:
            syncing = current
            for state in (
                OrderState.EXTRACTED,
                OrderState.VALIDATED,
                OrderState.READY_FOR_APPROVAL,
                OrderState.APPROVED,
                OrderState.SYNCING,
            ):
                syncing = syncing.transition_to(state)
            failed = syncing.transition_to(OrderState.FAILED_RETRYABLE)
            events.extend(
                (
                    _audit(
                        order_id,
                        "ORDER_EXTRACTION_COMPLETED",
                        10,
                        base_time=base_time,
                    ),
                    _audit(order_id, "ORDER_APPROVED", 11, base_time=base_time),
                )
            )
        else:
            raise AssertionError(origin)
        await update_order_snapshot(session, failed)
        for event in events:
            await _insert_audit(session, event)


async def _reviewer_retry(
    engine: AsyncEngine,
    order_id: UUID,
    *,
    recorded_at: datetime = BASE_TIME + timedelta(minutes=1),
) -> None:
    async with AsyncSession(engine) as session:
        persisted = await get_order_for_update(session, order_id)
        assert persisted is not None
        latest_audit_id = await get_latest_audit_event_id(session, order_id)
        await session.rollback()
        etag = compute_review_etag(
            order_id,
            persisted.order.state,
            persisted.order.failure_origin,
            None,
            None,
            latest_audit_id,
        )
        result = await retry_order(session, order_id, etag, REVIEWER, recorded_at)
        assert result.state in {
            OrderState.PROCESSING,
            OrderState.EXTRACTED,
            OrderState.SYNCING,
        }
        assert not session.in_transaction()


async def _events(engine: AsyncEngine, order_id: UUID) -> tuple[AuditEvent, ...]:
    async with AsyncSession(engine) as session:
        return await get_audit_events(session, order_id)


def _audit(
    order_id: UUID,
    event_type: str,
    seconds: int,
    *,
    base_time: datetime = BASE_TIME,
) -> AuditEvent:
    return AuditEvent(
        id=uuid4(),
        order_id=order_id,
        event_type=event_type,
        actor=ORCHESTRATION_ACTOR,
        occurred_at=base_time + timedelta(seconds=seconds),
        description=f"synthetic {event_type}",
    )


async def _insert_audit(session: AsyncSession, event: AuditEvent) -> None:
    session.add(
        AuditEventModel(
            id=event.id,
            order_id=event.order_id,
            event_type=event.event_type,
            actor=event.actor,
            occurred_at=event.occurred_at,
            description=event.description,
        )
    )
    await session.flush()


async def _delete_orders(engine: AsyncEngine, order_ids: tuple[UUID, ...]) -> None:
    async with engine.begin() as connection:
        for model in (
            ReviewRevisionModel,
            ExtractionSnapshotModel,
            ValidationIssueModel,
            AuditEventModel,
            OrderLineModel,
            SourceDocumentModel,
            OrderCreationIdempotencyModel,
        ):
            await connection.execute(delete(model).where(model.order_id.in_(order_ids)))
        await connection.execute(delete(OrderModel).where(OrderModel.id.in_(order_ids)))
