"""PostgreSQL proofs for M10B Phase 7 intake ownership and fencing."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from opsflow.application.errors import IdempotencyConflictError, SourceIdentityMismatchError
from opsflow.application.orchestration import _persist_extraction_completed
from opsflow.application.orders import (
    CreateLineInput,
    CreateOrderInput,
    CreateSourceDocumentInput,
    create_order,
    fingerprint_order_request,
)
from opsflow.application.validation import validate_order
from opsflow.domain import AuditEvent, OrderState, SourceDocumentType
from opsflow.extraction.errors import ProviderError, ProviderTimeoutError
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.orchestration.claims import (
    IntakeClaimKind,
    OrchestrationSourceIdentity,
    claim_intake_execution,
)
from opsflow.orchestration.failures import (
    classify_processing_failure,
    persist_orchestration_failure,
)
from opsflow.orchestration.ownership import StaleIntakeOwnershipError
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
from opsflow.persistence.repositories import get_audit_events, get_order, insert_audit_event
from opsflow.settings import Settings
from opsflow.validation import TrustedBusinessData, ValidationContext
from opsflow.validation.policy import ValidationPolicy

BASE_TIME = datetime(2030, 1, 1, tzinfo=UTC)


def test_initial_claim_has_durable_ownership() -> None:
    asyncio.run(_assert_initial_claim_has_durable_ownership())


async def _assert_initial_claim_has_durable_ownership() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        claim = await _claim(engine, persisted, request, key)
        assert claim.kind is IntakeClaimKind.INITIAL
        assert claim.ownership_token is not None
        assert claim.ownership_expires_at is not None
        row = await _ownership_row(engine, persisted.order.id)
        assert row == (claim.ownership_token, claim.ownership_expires_at)
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_active_duplicate_stands_down_without_rotating_ownership() -> None:
    asyncio.run(_assert_active_duplicate_stands_down_without_rotating_ownership())


async def _assert_active_duplicate_stands_down_without_rotating_ownership() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        before_events = await _events(engine, persisted.order.id)
        second = await _claim(engine, persisted, request, key)
        assert second.kind is IntakeClaimKind.STAND_DOWN
        assert second.retry_after_seconds is not None
        assert 1 <= second.retry_after_seconds <= 210
        assert await _ownership_row(engine, persisted.order.id) == (
            first.ownership_token,
            first.ownership_expires_at,
        )
        assert await _events(engine, persisted.order.id) == before_events
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_expired_unknown_audit_history_stands_down_without_recovery() -> None:
    asyncio.run(_assert_expired_invalid_history_stands_down("UNKNOWN_AUDIT_EVENT"))


def test_expired_impossible_audit_history_stands_down_without_recovery() -> None:
    asyncio.run(_assert_expired_invalid_history_stands_down("ORDER_APPROVED"))


async def _assert_expired_invalid_history_stands_down(event_type: str) -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        async with AsyncSession(engine) as session, session.begin():
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=persisted.order.id,
                    event_type=event_type,
                    actor="synthetic:test",
                    occurred_at=BASE_TIME + timedelta(seconds=1),
                    description="synthetic invalid lifecycle history",
                ),
            )
        await _expire_ownership(engine, persisted.order.id)

        redelivery = await _claim(engine, persisted, request, key)

        assert redelivery.kind is IntakeClaimKind.STAND_DOWN
        assert redelivery.retry_after_seconds is None
        assert (await _ownership_row(engine, persisted.order.id))[0] == first.ownership_token
        events = await _events(engine, persisted.order.id)
        assert event_type in {event.event_type for event in events}
        assert "ORDER_PROCESSING_RECOVERED" not in {event.event_type for event in events}
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_stale_takeover_rotates_fence_and_records_recovery() -> None:
    asyncio.run(_assert_stale_takeover_rotates_fence_and_records_recovery())


async def _assert_stale_takeover_rotates_fence_and_records_recovery() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        await _expire_ownership(engine, persisted.order.id)
        recovered = await _claim(engine, persisted, request, key)
        assert recovered.kind is IntakeClaimKind.RECOVER_PROCESSING
        assert recovered.ownership_token != first.ownership_token
        assert recovered.ownership_expires_at is not None
        events = await _events(engine, persisted.order.id)
        event_types = {event.event_type for event in events}
        assert {
            "ORDER_RECEIVED",
            "ORDER_PROCESSING_STARTED",
            "ORDER_PROCESSING_RECOVERED",
        } <= event_types
        recovery_events = [
            event for event in events if event.event_type == "ORDER_PROCESSING_RECOVERED"
        ]
        assert len(recovery_events) == 1
        assert "token" not in recovery_events[0].description.lower()
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_concurrent_stale_takeover_has_one_winner() -> None:
    asyncio.run(_assert_concurrent_stale_takeover_has_one_winner())


async def _assert_concurrent_stale_takeover_has_one_winner() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        await _claim(engine, persisted, request, key)
        await _expire_ownership(engine, persisted.order.id)
        first, second = await asyncio.gather(
            _claim(engine, persisted, request, key),
            _claim(engine, persisted, request, key),
        )
        assert [claim.kind for claim in (first, second)].count(
            IntakeClaimKind.RECOVER_PROCESSING
        ) == 1
        assert [claim.kind for claim in (first, second)].count(IntakeClaimKind.STAND_DOWN) == 1
        tokens = [claim.ownership_token for claim in (first, second)]
        assert tokens.count(None) == 1
        assert len({token for token in tokens if token is not None}) == 1
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_stale_worker_cannot_persist_extraction_completion() -> None:
    asyncio.run(_assert_stale_worker_cannot_persist_extraction_completion())


async def _assert_stale_worker_cannot_persist_extraction_completion() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        await _expire_ownership(engine, persisted.order.id)
        second = await _claim(engine, persisted, request, key)
        assert second.ownership_token != first.ownership_token
        with pytest.raises(StaleIntakeOwnershipError):
            async with AsyncSession(engine) as session:
                await _persist_extraction_completed(
                    session,
                    order_id=persisted.order.id,
                    ownership_token=first.ownership_token,
                    actor="orchestration:n8n",
                    recorded_at=BASE_TIME + timedelta(seconds=1),
                )
        async with AsyncSession(engine) as session:
            order = await get_order(session, persisted.order.id)
        assert order is not None and order.order.state is OrderState.PROCESSING
        assert "ORDER_PROCESSING_RECOVERED" in {
            event.event_type for event in await _events(engine, persisted.order.id)
        }
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_stale_worker_cannot_persist_failure() -> None:
    asyncio.run(_assert_stale_worker_cannot_persist_failure())


async def _assert_stale_worker_cannot_persist_failure() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        await _expire_ownership(engine, persisted.order.id)
        second = await _claim(engine, persisted, request, key)
        classification = classify_processing_failure(ProviderTimeoutError("synthetic"))
        with pytest.raises(StaleIntakeOwnershipError):
            async with AsyncSession(engine) as session:
                await persist_orchestration_failure(
                    session,
                    order_id=persisted.order.id,
                    classification=classification,
                    actor="orchestration:n8n",
                    recorded_at=BASE_TIME + timedelta(seconds=1),
                    review_base_url="http://localhost:5173",
                    ownership_token=first.ownership_token,
                )
        async with AsyncSession(engine) as session:
            order = await get_order(session, persisted.order.id)
        assert order is not None and order.order.state is OrderState.PROCESSING
        assert (await _ownership_row(engine, persisted.order.id))[0] == second.ownership_token
        assert "ORDER_PROCESSING_FAILED" not in {
            event.event_type for event in await _events(engine, persisted.order.id)
        }
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_stale_worker_cannot_persist_validation_promotion() -> None:
    asyncio.run(_assert_stale_worker_cannot_persist_validation_promotion())


async def _assert_stale_worker_cannot_persist_validation_promotion() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        async with AsyncSession(engine) as session:
            await _persist_extraction_completed(
                session,
                order_id=persisted.order.id,
                ownership_token=first.ownership_token,
                actor="orchestration:n8n",
                recorded_at=BASE_TIME + timedelta(seconds=1),
            )
        await _expire_ownership(engine, persisted.order.id)
        second = await _claim(engine, persisted, request, key)
        assert second.kind is IntakeClaimKind.RECOVER_EXTRACTED
        source_input = request.source_documents[0]
        source = persisted.order.source_documents[0]
        draft = ExtractionDraft(
            source_sha256=source_input.sha256,
            source_document_type=source_input.document_type,
            customer_name=None,
            customer_reference=None,
            po_number="PO-M10B-VALIDATION",
            order_date=date(2030, 1, 1),
            requested_delivery_date=date(2030, 1, 10),
            currency="USD",
            lines=(
                ExtractedLine(
                    sku="SKU-M10B",
                    description="M10B ownership fixture",
                    quantity=Decimal("1"),
                    submitted_price=Decimal("10"),
                ),
            ),
            notes=None,
            evidence=(),
        )

        class EmptyBusinessDataProvider:
            async def get_validation_data(self, request: object) -> TrustedBusinessData:
                del request
                return TrustedBusinessData((), (None,))

        with pytest.raises(StaleIntakeOwnershipError):
            async with AsyncSession(engine) as session:
                await validate_order(
                    session,
                    persisted.order.id,
                    source.id,
                    draft,
                    EmptyBusinessDataProvider(),
                    ValidationPolicy(
                        supported_currencies=("USD",),
                        price_tolerance_fraction=Decimal("0"),
                        high_value_threshold=Decimal("1000"),
                    ),
                    ValidationContext(evaluation_date=date(2030, 1, 1)),
                    BASE_TIME + timedelta(seconds=2),
                    "http://localhost:5173",
                    ownership_token=first.ownership_token,
                )
        async with AsyncSession(engine) as session:
            order = await get_order(session, persisted.order.id)
        assert order is not None and order.order.state is OrderState.EXTRACTED
        assert (await _ownership_row(engine, persisted.order.id))[0] == second.ownership_token
        assert "ORDER_VALIDATED" not in {
            event.event_type for event in await _events(engine, persisted.order.id)
        }
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_intermediate_extraction_keeps_ownership_active() -> None:
    asyncio.run(_assert_intermediate_extraction_keeps_ownership_active())


async def _assert_intermediate_extraction_keeps_ownership_active() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        async with AsyncSession(engine) as session:
            await _persist_extraction_completed(
                session,
                order_id=persisted.order.id,
                ownership_token=first.ownership_token,
                actor="orchestration:n8n",
                recorded_at=BASE_TIME + timedelta(seconds=1),
            )
        async with AsyncSession(engine) as session:
            order = await get_order(session, persisted.order.id)
        assert order is not None
        assert order.intake_claim_token == first.ownership_token
        assert order.intake_claim_expires_at is not None
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_terminal_validation_releases_ownership() -> None:
    asyncio.run(_assert_terminal_validation_releases_ownership())


async def _assert_terminal_validation_releases_ownership() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        claim = await _claim(engine, persisted, request, key)
        async with AsyncSession(engine) as session:
            await _persist_extraction_completed(
                session,
                order_id=persisted.order.id,
                ownership_token=claim.ownership_token,
                actor="orchestration:n8n",
                recorded_at=BASE_TIME + timedelta(seconds=1),
            )

        source_input = request.source_documents[0]
        source = persisted.order.source_documents[0]
        draft = ExtractionDraft(
            source_sha256=source_input.sha256,
            source_document_type=source_input.document_type,
            customer_name=None,
            customer_reference=None,
            po_number="PO-M10B-TERMINAL",
            order_date=date(2030, 1, 1),
            requested_delivery_date=date(2030, 1, 10),
            currency="USD",
            lines=(
                ExtractedLine(
                    sku="SKU-M10B",
                    description="M10B terminal fixture",
                    quantity=Decimal("1"),
                    submitted_price=Decimal("10"),
                ),
            ),
            notes=None,
            evidence=(),
        )

        class EmptyBusinessDataProvider:
            async def get_validation_data(self, request: object) -> TrustedBusinessData:
                del request
                return TrustedBusinessData((), (None,))

        async with AsyncSession(engine) as session:
            result = await validate_order(
                session,
                persisted.order.id,
                source.id,
                draft,
                EmptyBusinessDataProvider(),
                ValidationPolicy(
                    supported_currencies=("USD",),
                    price_tolerance_fraction=Decimal("0"),
                    high_value_threshold=Decimal("1000"),
                ),
                ValidationContext(evaluation_date=date(2030, 1, 1)),
                BASE_TIME + timedelta(seconds=2),
                "http://localhost:5173",
                ownership_token=claim.ownership_token,
            )

        assert result.order.state is OrderState.NEEDS_REVIEW
        assert await _ownership_row(engine, persisted.order.id) == (None, None)
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (ProviderTimeoutError("synthetic-timeout"), OrderState.FAILED_RETRYABLE),
        (ProviderError("synthetic-invalid-response"), OrderState.FAILED_FINAL),
    ],
)
def test_terminal_failure_releases_ownership(
    error: BaseException,
    expected_state: OrderState,
) -> None:
    asyncio.run(_assert_terminal_failure_releases_ownership(error, expected_state))


async def _assert_terminal_failure_releases_ownership(
    error: BaseException,
    expected_state: OrderState,
) -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        claim = await _claim(engine, persisted, request, key)
        async with AsyncSession(engine) as session:
            failed = await persist_orchestration_failure(
                session,
                order_id=persisted.order.id,
                classification=classify_processing_failure(error),
                actor="orchestration:n8n",
                recorded_at=BASE_TIME + timedelta(seconds=1),
                review_base_url="http://localhost:5173",
                ownership_token=claim.ownership_token,
            )
        assert failed.order.state is expected_state
        assert await _ownership_row(engine, persisted.order.id) == (None, None)
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def test_claim_survives_lost_result_persistence_and_recovers() -> None:
    asyncio.run(_assert_claim_survives_lost_result_persistence_and_recovers())


async def _assert_claim_survives_lost_result_persistence_and_recovers() -> None:
    engine = _engine()
    recovery_engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        await engine.dispose()
        await _expire_ownership(recovery_engine, persisted.order.id)
        recovered = await _claim(recovery_engine, persisted, request, key)
        assert recovered.kind is IntakeClaimKind.RECOVER_PROCESSING
        assert recovered.ownership_token != first.ownership_token
    finally:
        await _delete_order(recovery_engine, persisted.order.id)
        await recovery_engine.dispose()


def test_provider_result_cannot_persist_after_recovery_takeover() -> None:
    asyncio.run(_assert_provider_result_cannot_persist_after_recovery_takeover())


async def _assert_provider_result_cannot_persist_after_recovery_takeover() -> None:
    engine = _engine()
    recovery_engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        provider_result = {"provider_result": "held only in worker memory"}
        assert provider_result
        await _expire_ownership(recovery_engine, persisted.order.id)
        recovered = await _claim(recovery_engine, persisted, request, key)
        assert recovered.kind is IntakeClaimKind.RECOVER_PROCESSING
        with pytest.raises(StaleIntakeOwnershipError):
            async with AsyncSession(engine) as session:
                await _persist_extraction_completed(
                    session,
                    order_id=persisted.order.id,
                    ownership_token=first.ownership_token,
                    actor="orchestration:n8n",
                    recorded_at=BASE_TIME + timedelta(seconds=1),
                )
    finally:
        await _delete_order(recovery_engine, persisted.order.id)
        await engine.dispose()
        await recovery_engine.dispose()


def test_stale_identity_mismatch_cannot_take_over_expired_owner() -> None:
    asyncio.run(_assert_stale_identity_mismatch_cannot_take_over_expired_owner())


async def _assert_stale_identity_mismatch_cannot_take_over_expired_owner() -> None:
    engine = _engine()
    persisted, request, key = await _create_order(engine)
    try:
        first = await _claim(engine, persisted, request, key)
        await _expire_ownership(engine, persisted.order.id)
        with pytest.raises(IdempotencyConflictError):
            await _claim(
                engine,
                persisted,
                request,
                key,
                request_fingerprint=fingerprint_order_request(
                    replace(request, po_number="PO-DIFFERENT")
                ),
            )
        with pytest.raises(SourceIdentityMismatchError):
            await _claim(
                engine,
                persisted,
                request,
                key,
                source=replace(_source(persisted, request), sha256="b" * 64),
            )
        assert (await _ownership_row(engine, persisted.order.id))[0] == first.ownership_token
        recovered = await _claim(engine, persisted, request, key)
        assert recovered.kind is IntakeClaimKind.RECOVER_PROCESSING
    finally:
        await _delete_order(engine, persisted.order.id)
        await engine.dispose()


def _engine() -> AsyncEngine:
    return create_async_engine(Settings().database_url)


async def _create_order(engine: AsyncEngine):
    request = CreateOrderInput(
        customer_reference="CUST-M10B",
        po_number=f"PO-{uuid4()}",
        currency="USD",
        lines=(
            CreateLineInput(
                sku="SKU-M10B",
                description="M10B ownership fixture",
                quantity=Decimal("1"),
                submitted_price=Decimal("10"),
            ),
        ),
        source_documents=(
            CreateSourceDocumentInput(
                document_type=SourceDocumentType.PDF,
                name="m10b.pdf",
                mime_type="application/pdf",
                sha256="a" * 64,
                message_id=f"m10b-{uuid4()}",
            ),
        ),
    )
    key = f"m10b-{uuid4()}"
    async with AsyncSession(engine) as session:
        persisted = await create_order(session, request, key, now=BASE_TIME - timedelta(minutes=1))
    return persisted, request, key


async def _claim(
    engine: AsyncEngine,
    persisted,
    request: CreateOrderInput,
    key: str,
    *,
    source: OrchestrationSourceIdentity | None = None,
    request_fingerprint: str | None = None,
):
    async with AsyncSession(engine) as session:
        return await claim_intake_execution(
            session,
            order_id=persisted.order.id,
            idempotency_key=key,
            request_fingerprint=request_fingerprint or fingerprint_order_request(request),
            source=source or _source(persisted, request),
            actor="orchestration:n8n",
            recorded_at=BASE_TIME,
        )


def _source(persisted, request: CreateOrderInput) -> OrchestrationSourceIdentity:
    source = request.source_documents[0]
    return OrchestrationSourceIdentity(
        document_type=source.document_type,
        name=source.name,
        mime_type=source.mime_type,
        sha256=source.sha256,
        message_id=source.message_id,
    )


async def _expire_ownership(engine: AsyncEngine, order_id: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            update(OrderModel)
            .where(OrderModel.id == order_id)
            .values(intake_claim_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )


async def _ownership_row(engine: AsyncEngine, order_id: UUID):
    async with AsyncSession(engine) as session:
        row = await session.execute(
            select(OrderModel.intake_claim_token, OrderModel.intake_claim_expires_at).where(
                OrderModel.id == order_id
            )
        )
        values = row.one()
        return values[0], values[1]


async def _events(engine: AsyncEngine, order_id: UUID) -> tuple[AuditEvent, ...]:
    async with AsyncSession(engine) as session:
        return await get_audit_events(session, order_id)


async def _delete_order(engine: AsyncEngine, order_id: UUID) -> None:
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
            await connection.execute(delete(model).where(model.order_id == order_id))
        await connection.execute(delete(OrderModel).where(OrderModel.id == order_id))
