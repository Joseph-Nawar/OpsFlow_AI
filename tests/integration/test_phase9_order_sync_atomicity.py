"""PostgreSQL proofs for atomic Phase 9 approval intent and retry recovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from test_phase6_commands import (
    APPROVER_TOKEN,
    REVIEWER_TOKEN,
    _case,
    _command_client,
    _etag_from_detail,
    _get_detail,
    _post_command,
    _read_order_and_audits,
)

from opsflow.application import review_commands
from opsflow.order_sync.contracts import OrderSyncStep
from opsflow.persistence.models import AuditEventModel, OrderModel, OrderSyncModel
from opsflow.persistence.order_sync_repository import insert_order_sync_intent

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def test_approval_commits_exactly_one_sync_intent() -> None:
    asyncio.run(_assert_approval_commits_one_sync_intent())


async def _assert_approval_commits_one_sync_intent() -> None:
    case = _case(review_commands.OrderState.READY_FOR_APPROVAL)
    async with _command_client((case,)) as (client, session_factory, _):
        detail = await _get_detail(client, case.order_id, APPROVER_TOKEN)
        response = await _post_command(
            client,
            "approve",
            case.order_id,
            APPROVER_TOKEN,
            _etag_from_detail(detail),
        )
        async with session_factory() as session:
            sync_count = await session.scalar(
                select(func.count())
                .select_from(OrderSyncModel)
                .where(OrderSyncModel.order_id == case.order_id)
            )
            event = await session.scalar(
                select(AuditEventModel).where(
                    AuditEventModel.order_id == case.order_id,
                    AuditEventModel.event_type == "ORDER_APPROVED",
                )
            )
            order = await session.get(OrderModel, case.order_id)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "APPROVED"
    assert sync_count == 1
    assert event is not None
    assert order is not None and order.state == "APPROVED"


def test_sync_intent_failure_rolls_back_approval_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_assert_sync_intent_failure_rolls_back(monkeypatch))


async def _assert_sync_intent_failure_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(review_commands.OrderState.READY_FOR_APPROVAL)
    real_insert = review_commands.create_order_sync_intent

    async def fail_after_insert(
        session: AsyncSession, order_id: object, created_at: datetime
    ) -> None:
        await real_insert(session, order_id, created_at)
        raise IntegrityError("synthetic sync intent failure", {}, RuntimeError("private detail"))

    monkeypatch.setattr(review_commands, "create_order_sync_intent", fail_after_insert)
    async with _command_client((case,)) as (client, session_factory, _):
        detail = await _get_detail(client, case.order_id, APPROVER_TOKEN)
        before_order, before_audits = await _read_order_and_audits(session_factory, case.order_id)
        response = await _post_command(
            client,
            "approve",
            case.order_id,
            APPROVER_TOKEN,
            _etag_from_detail(detail),
        )
        after_order, after_audits = await _read_order_and_audits(session_factory, case.order_id)
        async with session_factory() as session:
            sync_count = await session.scalar(
                select(func.count())
                .select_from(OrderSyncModel)
                .where(OrderSyncModel.order_id == case.order_id)
            )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVIEW_PERSISTENCE_CONFLICT"
    assert "private detail" not in response.text
    assert after_order == before_order
    assert after_audits == before_audits
    assert sync_count == 0


def test_duplicate_sync_intent_is_rejected() -> None:
    asyncio.run(_assert_duplicate_sync_intent_is_rejected())


async def _assert_duplicate_sync_intent_is_rejected() -> None:
    case = _case(review_commands.OrderState.READY_FOR_APPROVAL)
    async with _command_client((case,)) as (_, session_factory, _):
        async with session_factory() as session, session.begin():
            await insert_order_sync_intent(session, case.order_id, _NOW)
        async with session_factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    await insert_order_sync_intent(session, case.order_id, _NOW)


def test_sync_retry_resets_generation_without_losing_receipts() -> None:
    asyncio.run(_assert_sync_retry_resets_generation_without_losing_receipts())


async def _assert_sync_retry_resets_generation_without_losing_receipts() -> None:
    case = _case(
        review_commands.OrderState.FAILED_RETRYABLE,
        failure_origin=review_commands.OrderState.SYNCING,
    )
    async with _command_client((case,)) as (client, session_factory, _):
        claim_token = uuid4()
        expiry = _NOW + timedelta(minutes=5)
        async with session_factory() as session:
            row = await session.get(OrderSyncModel, case.order_id)
            assert row is not None
            row.claim_token = claim_token
            row.claim_expires_at = expiry
            row.attempt_count = 3
            row.retry_generation = 10_000
            row.next_attempt_at = _NOW + timedelta(minutes=10)
            row.odoo_sale_order_id = 101
            row.odoo_sale_order_name = "S00101"
            row.hubspot_company_id = "company-1"
            row.in_flight_step = OrderSyncStep.HUBSPOT_DEAL.value
            row.last_failure_step = OrderSyncStep.HUBSPOT_DEAL.value
            row.last_failure_code = "PROVIDER_UNAVAILABLE"
            row.last_attempt_at = _NOW
            await session.commit()

        detail = await _get_detail(client, case.order_id, REVIEWER_TOKEN)
        response = await _post_command(
            client,
            "retry",
            case.order_id,
            REVIEWER_TOKEN,
            _etag_from_detail(detail),
        )

        async with session_factory() as session:
            row = await session.get(OrderSyncModel, case.order_id)
            order = await session.get(OrderModel, case.order_id)
            database_now = await session.scalar(select(func.now()))

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "SYNCING"
    assert row is not None
    assert row.retry_generation == 10_001
    assert row.attempt_count == 0
    assert row.next_attempt_at <= database_now
    assert row.claim_token is None and row.claim_expires_at is None
    assert row.odoo_sale_order_id == 101 and row.odoo_sale_order_name == "S00101"
    assert row.hubspot_company_id == "company-1"
    assert row.hubspot_deal_id is None
    assert row.in_flight_step == OrderSyncStep.HUBSPOT_DEAL.value
    assert order is not None and order.state == "SYNCING" and order.failure_origin is None
