"""PostgreSQL proofs for M9B claims, leases, receipts, retries, and completion."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from opsflow.application.order_sync import (
    OrderSyncCompletionError,
    OrderSyncStepPreconditionError,
    StaleOrderSyncClaimError,
    begin_order_sync_step,
    claim_next_order_sync,
    complete_order_sync,
    persist_order_sync_receipt,
    record_order_sync_failure,
    yield_order_sync_claim,
)
from opsflow.domain import OrderState
from opsflow.order_sync.contracts import (
    HubSpotAssociationReceipt,
    HubSpotCompanyReceipt,
    HubSpotDealReceipt,
    OdooOrderReceipt,
    OrderSync,
    OrderSyncFailureCode,
    OrderSyncStep,
)
from opsflow.persistence.models import AuditEventModel, OrderModel, OrderSyncModel
from opsflow.persistence.order_sync_repository import claim_one_eligible_order_sync
from opsflow.settings import Settings

REPOSITORY_ROOT = Path(__file__).parents[2]
_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def test_non_approved_order_cannot_be_claimed() -> None:
    asyncio.run(_assert_non_approved_order_cannot_be_claimed())


async def _assert_non_approved_order_cannot_be_claimed() -> None:
    async with (
        _sync_database(state=OrderState.NEEDS_REVIEW) as (session_factory, order_id),
        session_factory() as session,
    ):
        candidate = await claim_one_eligible_order_sync(session)
        assert candidate is None or candidate[0].order_id != order_id
        row = await session.get(OrderSyncModel, order_id)
        order = await session.get(OrderModel, order_id)
    assert row is not None and row.claim_token is None
    assert order is not None and order.state == OrderState.NEEDS_REVIEW.value


def test_first_claim_transitions_approved_to_syncing_and_audits() -> None:
    asyncio.run(_assert_first_claim_transitions_and_audits())


async def _assert_first_claim_transitions_and_audits() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            claim = await claim_next_order_sync(session)
        assert claim is not None
        async with session_factory() as session:
            order = await session.get(OrderModel, order_id)
            events = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
    assert order is not None and order.state == OrderState.SYNCING.value
    assert [event.event_type for event in events] == ["ORDER_SYNC_STARTED"]


def test_concurrent_claims_have_one_owner() -> None:
    asyncio.run(_assert_concurrent_claims_have_one_owner())


async def _assert_concurrent_claims_have_one_owner() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as first_session, session_factory() as second_session:
            first, second = await asyncio.gather(
                claim_next_order_sync(first_session),
                claim_next_order_sync(second_session),
            )
        claims = [claim for claim in (first, second) if claim is not None]
        assert len(claims) == 1
        assert claims[0].order_id == order_id


def test_active_lease_is_not_stolen() -> None:
    asyncio.run(_assert_active_lease_is_not_stolen())


async def _assert_active_lease_is_not_stolen() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            first = await claim_next_order_sync(session)
        assert first is not None
        async with session_factory() as session:
            second = await claim_next_order_sync(session)
            row = await session.get(OrderSyncModel, order_id)
    assert second is None
    assert row is not None
    assert row.claim_token == first.claim_token
    assert row.claim_expires_at == first.claim_expires_at


def test_stale_token_cannot_mutate_sync() -> None:
    asyncio.run(_assert_stale_token_cannot_mutate_sync())


async def _assert_stale_token_cannot_mutate_sync() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            stale = await claim_next_order_sync(session)
        assert stale is not None
        async with session_factory() as session:
            await begin_order_sync_step(
                session, order_id, stale.claim_token, OrderSyncStep.ODOO_BRIDGE
            )
        await _expire_claim(session_factory, order_id)
        async with session_factory() as session:
            current = await claim_next_order_sync(session)
        assert current is not None and current.claim_token != stale.claim_token

        async with session_factory() as session:
            with pytest.raises(StaleOrderSyncClaimError):
                await persist_order_sync_receipt(
                    session, order_id, stale.claim_token, OdooOrderReceipt(42, "S00042")
                )
        async with session_factory() as session:
            row = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
    assert row is not None
    assert row.claim_token == current.claim_token
    assert row.odoo_sale_order_id is None
    assert row.in_flight_step == OrderSyncStep.ODOO_BRIDGE.value
    assert order is not None and order.state == OrderState.SYNCING.value


def test_expired_lease_rotates_token_and_counts_one_recovery() -> None:
    asyncio.run(_assert_expired_lease_rotates_token_and_counts_one_recovery())


async def _assert_expired_lease_rotates_token_and_counts_one_recovery() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            original = await claim_next_order_sync(session)
        assert original is not None
        async with session_factory() as session:
            await begin_order_sync_step(
                session, order_id, original.claim_token, OrderSyncStep.ODOO_BRIDGE
            )
        await _expire_claim(session_factory, order_id)
        async with session_factory() as session:
            recovered = await claim_next_order_sync(session)
            row = await session.get(OrderSyncModel, order_id)
    assert recovered is not None and recovered.claim_token != original.claim_token
    assert row is not None
    assert row.attempt_count == 1
    assert row.in_flight_step == OrderSyncStep.ODOO_BRIDGE.value
    assert row.claim_token == recovered.claim_token


def test_terminal_sync_is_not_claimed_again() -> None:
    asyncio.run(_assert_terminal_sync_is_not_claimed_again())


async def _assert_terminal_sync_is_not_claimed_again() -> None:
    async with (
        _sync_database(state=OrderState.COMPLETED, full_receipts=True) as (
            session_factory,
            order_id,
        ),
        session_factory() as session,
    ):
        candidate = await claim_one_eligible_order_sync(session)
        row = await session.get(OrderSyncModel, order_id)
    assert candidate is None or candidate[0].order_id != order_id
    assert row is not None and row.attempt_count == 0 and row.claim_token is None


def test_third_retryable_outcome_moves_order_to_failed_retryable() -> None:
    asyncio.run(_assert_third_retryable_outcome_moves_order_to_failed_retryable())


async def _assert_third_retryable_outcome_moves_order_to_failed_retryable() -> None:
    async with _sync_database() as (session_factory, order_id):
        for outcome in range(3):
            async with session_factory() as session:
                claim = await claim_next_order_sync(session)
            assert claim is not None
            async with session_factory() as session:
                await begin_order_sync_step(
                    session, order_id, claim.claim_token, OrderSyncStep.ODOO_LOOKUP
                )
            async with session_factory() as session:
                await record_order_sync_failure(
                    session,
                    order_id,
                    claim.claim_token,
                    OrderSyncStep.ODOO_LOOKUP,
                    OrderSyncFailureCode.PROVIDER_UNAVAILABLE,
                )
            if outcome < 2:
                await _make_due(session_factory, order_id)
        async with session_factory() as session:
            row = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
    assert row is not None
    assert row.attempt_count == 3
    assert row.claim_token is None and row.claim_expires_at is None
    assert row.last_failure_code == OrderSyncFailureCode.PROVIDER_UNAVAILABLE.value
    assert order is not None
    assert order.state == OrderState.FAILED_RETRYABLE.value
    assert order.failure_origin == OrderState.SYNCING.value


def test_permanent_reconciliation_failure_moves_order_to_failed_final() -> None:
    asyncio.run(_assert_permanent_reconciliation_failure_moves_order_to_failed_final())


async def _assert_permanent_reconciliation_failure_moves_order_to_failed_final() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            claim = await claim_next_order_sync(session)
        assert claim is not None
        async with session_factory() as session:
            await begin_order_sync_step(
                session, order_id, claim.claim_token, OrderSyncStep.ODOO_BRIDGE
            )
        async with session_factory() as session:
            await record_order_sync_failure(
                session,
                order_id,
                claim.claim_token,
                OrderSyncStep.ODOO_BRIDGE,
                OrderSyncFailureCode.IDEMPOTENCY_CONFLICT,
            )
        async with session_factory() as session:
            order = await session.get(OrderModel, order_id)
            row = await session.get(OrderSyncModel, order_id)
    assert order is not None
    assert order.state == OrderState.FAILED_FINAL.value
    assert order.failure_origin == OrderState.SYNCING.value
    assert row is not None and row.attempt_count == 0 and row.claim_token is None


def test_budget_yield_after_receipt_preserves_checkpoint_without_counting_attempt() -> None:
    asyncio.run(_assert_budget_yield_preserves_receipt())


async def _assert_budget_yield_preserves_receipt() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            claim = await claim_next_order_sync(session)
        assert claim is not None
        async with session_factory() as session:
            await begin_order_sync_step(
                session, order_id, claim.claim_token, OrderSyncStep.ODOO_BRIDGE
            )
        async with session_factory() as session:
            await persist_order_sync_receipt(
                session, order_id, claim.claim_token, OdooOrderReceipt(43, "S00043")
            )
        async with session_factory() as session:
            yielded = await yield_order_sync_claim(session, order_id, claim.claim_token)
        async with session_factory() as session:
            row = await session.get(OrderSyncModel, order_id)
            database_now = await session.scalar(select(func.now()))
    assert yielded.attempt_count == 0
    assert yielded.odoo_sale_order_id == 43
    assert row is not None
    assert row.claim_token is None and row.claim_expires_at is None
    assert row.attempt_count == 0
    assert row.odoo_sale_order_id == 43 and row.odoo_sale_order_name == "S00043"
    assert row.in_flight_step is None
    assert row.next_attempt_at <= database_now


def test_retry_after_never_shortens_base_delay() -> None:
    asyncio.run(_assert_retry_after_never_shortens_base_delay())


async def _assert_retry_after_never_shortens_base_delay() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            first = await claim_next_order_sync(session)
        assert first is not None
        async with session_factory() as session:
            await begin_order_sync_step(
                session, order_id, first.claim_token, OrderSyncStep.ODOO_LOOKUP
            )
        async with session_factory() as session:
            await record_order_sync_failure(
                session,
                order_id,
                first.claim_token,
                OrderSyncStep.ODOO_LOOKUP,
                OrderSyncFailureCode.PROVIDER_RATE_LIMIT,
                retry_after=timedelta(seconds=5),
            )
        async with session_factory() as session:
            row = await session.get(OrderSyncModel, order_id)
            database_now = await session.scalar(select(func.now()))
        assert row is not None and row.next_attempt_at >= database_now + timedelta(seconds=29)

        await _make_due(session_factory, order_id)
        async with session_factory() as session:
            second = await claim_next_order_sync(session)
        assert second is not None
        async with session_factory() as session:
            await begin_order_sync_step(
                session, order_id, second.claim_token, OrderSyncStep.ODOO_LOOKUP
            )
        async with session_factory() as session:
            await record_order_sync_failure(
                session,
                order_id,
                second.claim_token,
                OrderSyncStep.ODOO_LOOKUP,
                OrderSyncFailureCode.PROVIDER_RATE_LIMIT,
                retry_after=timedelta(seconds=600),
            )
        async with session_factory() as session:
            row = await session.get(OrderSyncModel, order_id)
            database_now = await session.scalar(select(func.now()))
    assert row is not None
    assert row.next_attempt_at >= database_now + timedelta(seconds=599)


def test_step_checkpoint_requires_preceding_receipts() -> None:
    asyncio.run(_assert_step_checkpoint_requires_preceding_receipts())


async def _assert_step_checkpoint_requires_preceding_receipts() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            claim = await claim_next_order_sync(session)
        assert claim is not None
        async with session_factory() as session:
            with pytest.raises(OrderSyncStepPreconditionError):
                await begin_order_sync_step(
                    session, order_id, claim.claim_token, OrderSyncStep.HUBSPOT_DEAL
                )
        async with session_factory() as session:
            row = await session.get(OrderSyncModel, order_id)
    assert row is not None and row.in_flight_step is None


def test_completion_requires_all_four_receipts_and_is_terminal() -> None:
    asyncio.run(_assert_completion_requires_receipts_and_is_terminal())


async def _assert_completion_requires_receipts_and_is_terminal() -> None:
    async with _sync_database() as (session_factory, order_id):
        async with session_factory() as session:
            claim = await claim_next_order_sync(session)
        assert claim is not None
        async with session_factory() as session:
            with pytest.raises(OrderSyncCompletionError):
                await complete_order_sync(session, order_id, claim.claim_token)

        for step, receipt in (
            (OrderSyncStep.ODOO_BRIDGE, OdooOrderReceipt(44, "S00044")),
            (OrderSyncStep.HUBSPOT_COMPANY, HubSpotCompanyReceipt("company-44")),
            (OrderSyncStep.HUBSPOT_DEAL, HubSpotDealReceipt("deal-44")),
            (OrderSyncStep.HUBSPOT_ASSOCIATION, HubSpotAssociationReceipt(_NOW)),
        ):
            async with session_factory() as session:
                await begin_order_sync_step(session, order_id, claim.claim_token, step)
            async with session_factory() as session:
                await persist_order_sync_receipt(session, order_id, claim.claim_token, receipt)
        async with session_factory() as session:
            completed = await complete_order_sync(session, order_id, claim.claim_token)
        async with session_factory() as session:
            order = await session.get(OrderModel, order_id)
            events = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
        async with session_factory() as session:
            claim_after_completion = await claim_next_order_sync(session)
    assert isinstance(completed, OrderSync)
    assert completed.order_id == order_id
    assert completed.claim_token is None
    assert completed.in_flight_step is None
    assert order is not None and order.state == OrderState.COMPLETED.value
    assert [event.event_type for event in events] == [
        "ORDER_SYNC_STARTED",
        "ORDER_SYNC_COMPLETED",
    ]
    assert claim_after_completion is None


@asynccontextmanager
async def _sync_database(
    *, state: OrderState = OrderState.APPROVED, full_receipts: bool = False
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], UUID]]:
    _run_alembic("upgrade", "head")
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    order_id = uuid4()
    async with session_factory() as session:
        session.add(
            OrderModel(
                id=order_id,
                state=state.value,
                failure_origin=None,
                created_at=_NOW,
            )
        )
        session.add(
            OrderSyncModel(
                order_id=order_id,
                claim_token=None,
                claim_expires_at=None,
                attempt_count=0,
                retry_generation=0,
                next_attempt_at=datetime(1970, 1, 1, tzinfo=UTC),
                odoo_sale_order_id=101 if full_receipts else None,
                odoo_sale_order_name="S00101" if full_receipts else None,
                hubspot_company_id="company-101" if full_receipts else None,
                hubspot_deal_id="deal-101" if full_receipts else None,
                hubspot_association_confirmed_at=_NOW if full_receipts else None,
                in_flight_step=None,
                last_failure_step=None,
                last_failure_code=None,
                last_attempt_at=None,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        await session.commit()
    try:
        yield session_factory, order_id
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete_order(order_id))
        await engine.dispose()


async def _expire_claim(session_factory: async_sessionmaker[AsyncSession], order_id: UUID) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(OrderSyncModel)
            .where(OrderSyncModel.order_id == order_id)
            .values(claim_expires_at=func.now() - text("interval '1 second'"))
        )


async def _make_due(session_factory: async_sessionmaker[AsyncSession], order_id: UUID) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(
            update(OrderSyncModel)
            .where(OrderSyncModel.order_id == order_id)
            .values(next_attempt_at=func.now() - text("interval '1 second'"))
        )


def _run_alembic(*arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=REPOSITORY_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
    del result


def delete_order(order_id: UUID):
    return text("DELETE FROM orders WHERE id = :order_id").bindparams(order_id=order_id)
