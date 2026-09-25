"""PostgreSQL claim ownership, lease recovery, retry, and outcome proofs."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_phase6_revalidation import (
    StaticProvider,
    _case_client,
    _get_detail_etag,
    _make_case,
)

from opsflow.notifications.contracts import (
    NotificationFailureCode,
    NotificationOutcome,
    NotificationOutcomeKind,
    NotificationStatus,
)
from opsflow.notifications.service import (
    NotificationNotFoundError,
    StaleNotificationClaimError,
    claim_next_notification,
    record_notification_outcome,
)
from opsflow.persistence.models import (
    AuditEventModel,
    NotificationDeliveryModel,
    OrderModel,
    ReviewRevisionModel,
)
from opsflow.settings import Settings


def test_claim_returns_none_when_no_delivery_is_due() -> None:
    asyncio.run(_assert_no_due_delivery())


def test_claim_increments_once_and_lease_recovery_rotates_token() -> None:
    asyncio.run(_assert_claim_and_lease_recovery())


def test_independent_postgres_sessions_have_one_active_claim_owner() -> None:
    asyncio.run(_assert_concurrent_single_owner())


@pytest.mark.parametrize(("attempt", "delay"), [(1, 30), (2, 120)])
def test_failure_schedules_backend_owned_retry(attempt: int, delay: int) -> None:
    asyncio.run(_assert_retry(attempt, delay, hint=None, channel="SLACK"))


@pytest.mark.parametrize(("hint", "delay"), [(0, 30), (60, 60), (300, 300)])
def test_slack_retry_after_uses_maximum_of_base_and_bounded_hint(hint: int, delay: int) -> None:
    asyncio.run(_assert_retry(1, delay, hint=hint, channel="SLACK"))


def test_gmail_ignores_slack_retry_after_hint() -> None:
    asyncio.run(_assert_retry(1, 30, hint=300, channel="GMAIL"))


def test_attempt_three_failure_is_final_and_never_reclaimed() -> None:
    asyncio.run(_assert_attempt_three_final())


def test_expired_attempt_three_is_finalized_before_claim_selection() -> None:
    asyncio.run(_assert_expired_third_claim_finalized())


def test_delivered_outcome_persists_only_bounded_reference() -> None:
    asyncio.run(_assert_delivered_outcome())


def test_wrong_expired_reclaimed_and_terminal_tokens_are_stale_without_mutation() -> None:
    asyncio.run(_assert_stale_tokens_are_non_mutating())


def test_unknown_notification_is_distinct_from_stale_claim() -> None:
    asyncio.run(_assert_unknown_notification())


def test_pending_attempt_three_row_is_never_claimed_again() -> None:
    asyncio.run(_assert_no_fourth_claim_for_pending_attempt_three())


def test_claim_and_outcome_leave_review_etag_audit_and_revision_unchanged() -> None:
    asyncio.run(_assert_review_etag_isolated())


async def _seed_delivery(
    *,
    status: str = "PENDING",
    attempt_count: int = 0,
    channel: str = "SLACK",
    claim_token: UUID | None = None,
    claim_expires_at: datetime | None = None,
    next_attempt_at: datetime | None = None,
) -> tuple[object, async_sessionmaker, UUID, UUID]:
    engine = create_async_engine(Settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    order_id, event_id, delivery_id = uuid4(), uuid4(), uuid4()
    async with sessions() as session, session.begin():
        session.add(
            OrderModel(
                id=order_id,
                customer_reference="CUST-NOTIFY",
                po_number=f"PO-NOTIFY-{delivery_id.hex}",
                order_date=None,
                requested_delivery_date=None,
                currency="USD",
                state="NEEDS_REVIEW",
                failure_origin=None,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            AuditEventModel(
                id=event_id,
                order_id=order_id,
                event_type="ORDER_NEEDS_REVIEW",
                actor="system",
                occurred_at=now,
                description="Synthetic notification test event.",
            )
        )
        session.add(
            NotificationDeliveryModel(
                id=delivery_id,
                order_id=order_id,
                trigger_audit_event_id=event_id,
                channel=channel,
                kind="REVIEW_REQUIRED",
                payload={"text": "safe test payload"},
                status=status,
                attempt_count=attempt_count,
                claim_token=claim_token,
                claim_expires_at=claim_expires_at,
                next_attempt_at=next_attempt_at or now - timedelta(seconds=1),
                created_at=now,
                updated_at=now,
            )
        )
    return engine, sessions, delivery_id, order_id


async def _dispose(engine: object, sessions: async_sessionmaker, order_id: UUID) -> None:
    async with sessions() as session, session.begin():
        await session.execute(delete(OrderModel).where(OrderModel.id == order_id))
    await engine.dispose()


async def _assert_no_due_delivery() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    engine, sessions, notification_id, order_id = await _seed_delivery(next_attempt_at=future)
    try:
        async with sessions() as session:
            assert await claim_next_notification(session) is None
        async with sessions() as session:
            row = await session.get(NotificationDeliveryModel, notification_id)
            assert row is not None and row.attempt_count == 0 and row.status == "PENDING"
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_claim_and_lease_recovery() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery()
    try:
        async with sessions() as session:
            first = await claim_next_notification(session)
        assert first is not None and first.notification_id == notification_id
        assert first.attempt_number == 1
        assert abs((first.claim_expires_at - datetime.now(UTC)).total_seconds() - 300) < 2
        async with sessions() as session, session.begin():
            await session.execute(
                update(NotificationDeliveryModel)
                .where(NotificationDeliveryModel.id == notification_id)
                .values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        expired = NotificationOutcome(
            claim_token=first.claim_token,
            kind=NotificationOutcomeKind.DELIVERED,
            provider_reference="expired-provider-reference",
        )
        with pytest.raises(StaleNotificationClaimError):
            async with sessions() as session:
                await record_notification_outcome(session, notification_id, expired)
        async with sessions() as session:
            expired_row = await session.get(NotificationDeliveryModel, notification_id)
            assert expired_row is not None
            assert expired_row.status == "CLAIMED" and expired_row.claim_token == first.claim_token
            assert expired_row.provider_reference is None
        async with sessions() as session:
            second = await claim_next_notification(session)
        assert second is not None and second.attempt_number == 2
        assert second.claim_token != first.claim_token
        assert second.claim_expires_at > first.claim_expires_at
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_concurrent_single_owner() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery()
    barrier = asyncio.Barrier(2)
    try:

        async def claim() -> object:
            async with sessions() as session:
                await barrier.wait()
                return await claim_next_notification(session)

        first, second = await asyncio.gather(claim(), claim())
        claims = [item for item in (first, second) if item is not None]
        assert len(claims) == 1
        assert claims[0].notification_id == notification_id
        async with sessions() as session:
            row = await session.get(NotificationDeliveryModel, notification_id)
            assert row is not None
            assert row.status == "CLAIMED"
            assert row.attempt_count == 1
            assert row.claim_token == claims[0].claim_token
    finally:
        await _dispose(engine, sessions, order_id)


async def _claim_attempt(
    sessions: async_sessionmaker,
    notification_id: UUID,
    attempt: int,
) -> object:
    claim = None
    for _ in range(attempt):
        async with sessions() as session:
            claim = await claim_next_notification(session)
        assert claim is not None
        if claim.attempt_number < attempt:
            async with sessions() as session, session.begin():
                await session.execute(
                    update(NotificationDeliveryModel)
                    .where(NotificationDeliveryModel.id == notification_id)
                    .values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
    return claim


async def _assert_retry(attempt: int, delay: int, *, hint: int | None, channel: str) -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery(channel=channel)
    try:
        claim = await _claim_attempt(sessions, notification_id, attempt)
        outcome = NotificationOutcome(
            claim_token=claim.claim_token,
            kind=NotificationOutcomeKind.FAILED,
            failure_code=NotificationFailureCode.RATE_LIMITED,
            retry_after_seconds=hint,
        )
        async with sessions() as session:
            result = await record_notification_outcome(session, notification_id, outcome)
        assert result.status is NotificationStatus.PENDING
        assert result.attempt_count == attempt
        async with sessions() as session:
            row = await session.get(NotificationDeliveryModel, notification_id)
            assert row is not None
            assert row.status == "PENDING"
            assert row.claim_token is None and row.claim_expires_at is None
            assert row.last_failure_code == "RATE_LIMITED"
            assert (row.next_attempt_at - row.updated_at).total_seconds() == delay
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_attempt_three_final() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery()
    try:
        claim = await _claim_attempt(sessions, notification_id, 3)
        outcome = NotificationOutcome(
            claim_token=claim.claim_token,
            kind=NotificationOutcomeKind.FAILED,
            failure_code=NotificationFailureCode.TIMEOUT,
        )
        async with sessions() as session:
            result = await record_notification_outcome(session, notification_id, outcome)
        assert result.status is NotificationStatus.FAILED_FINAL
        assert result.attempt_count == 3
        async with sessions() as session:
            assert await claim_next_notification(session) is None
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_expired_third_claim_finalized() -> None:
    old_token = uuid4()
    engine, sessions, notification_id, order_id = await _seed_delivery(
        status="CLAIMED",
        attempt_count=3,
        claim_token=old_token,
        claim_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    try:
        async with sessions() as session:
            assert await claim_next_notification(session) is None
        async with sessions() as session:
            row = await session.get(NotificationDeliveryModel, notification_id)
            assert row is not None and row.status == "FAILED_FINAL"
            assert row.claim_token is None and row.claim_expires_at is None
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_delivered_outcome() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery()
    try:
        claim = await _claim_attempt(sessions, notification_id, 1)
        outcome = NotificationOutcome(
            claim_token=claim.claim_token,
            kind=NotificationOutcomeKind.DELIVERED,
            provider_reference="provider-message-123",
        )
        async with sessions() as session:
            result = await record_notification_outcome(session, notification_id, outcome)
        assert result.status is NotificationStatus.DELIVERED
        assert result.provider_reference == "provider-message-123"
        assert result.last_failure_code is None
        async with sessions() as session:
            row = await session.get(NotificationDeliveryModel, notification_id)
            assert row is not None and row.status == "DELIVERED"
            assert row.claim_token is None and row.claim_expires_at is None
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_stale_tokens_are_non_mutating() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery()
    try:
        first = await _claim_attempt(sessions, notification_id, 1)
        async with sessions() as session, session.begin():
            await session.execute(
                update(NotificationDeliveryModel)
                .where(NotificationDeliveryModel.id == notification_id)
                .values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        async with sessions() as session:
            second = await claim_next_notification(session)
        assert second is not None and second.attempt_number == 2
        stale = NotificationOutcome(
            claim_token=first.claim_token,
            kind=NotificationOutcomeKind.DELIVERED,
            provider_reference="stale-provider-reference",
        )
        with pytest.raises(StaleNotificationClaimError):
            async with sessions() as session:
                await record_notification_outcome(session, notification_id, stale)
        wrong = NotificationOutcome(
            claim_token=uuid4(),
            kind=NotificationOutcomeKind.DELIVERED,
        )
        with pytest.raises(StaleNotificationClaimError):
            async with sessions() as session:
                await record_notification_outcome(session, notification_id, wrong)
        async with sessions() as session:
            row = await session.get(NotificationDeliveryModel, notification_id)
            assert row is not None
            assert row.status == "CLAIMED" and row.claim_token == second.claim_token
            assert row.attempt_count == 2 and row.provider_reference is None
        delivered = NotificationOutcome(
            claim_token=second.claim_token,
            kind=NotificationOutcomeKind.DELIVERED,
        )
        async with sessions() as session:
            await record_notification_outcome(session, notification_id, delivered)
        with pytest.raises(StaleNotificationClaimError):
            async with sessions() as session:
                await record_notification_outcome(session, notification_id, delivered)
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_unknown_notification() -> None:
    engine = create_async_engine(Settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        with pytest.raises(NotificationNotFoundError):
            async with sessions() as session:
                await record_notification_outcome(
                    session,
                    uuid4(),
                    NotificationOutcome(
                        claim_token=uuid4(), kind=NotificationOutcomeKind.DELIVERED
                    ),
                )
    finally:
        await engine.dispose()


async def _assert_no_fourth_claim_for_pending_attempt_three() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery(attempt_count=3)
    try:
        async with sessions() as session:
            assert await claim_next_notification(session) is None
        async with sessions() as session:
            row = await session.get(NotificationDeliveryModel, notification_id)
            assert row is not None and row.attempt_count == 3 and row.status == "PENDING"
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_review_etag_isolated() -> None:
    case = _make_case()
    async with _case_client(case, StaticProvider()) as (client, sessions, _engine, _app):
        before_detail, before_etag = await _get_detail_etag(client, case.order_id)
        async with sessions() as session:
            before_audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.order_id == case.order_id)
            )
        async with sessions() as session, session.begin():
            event_id = await session.scalar(
                select(AuditEventModel.id)
                .where(AuditEventModel.order_id == case.order_id)
                .order_by(AuditEventModel.occurred_at, AuditEventModel.id)
                .limit(1)
            )
            assert event_id is not None
            now = datetime.now(UTC)
            session.add(
                NotificationDeliveryModel(
                    id=uuid4(),
                    order_id=case.order_id,
                    trigger_audit_event_id=event_id,
                    channel="SLACK",
                    kind="REVIEW_REQUIRED",
                    payload={"text": "safe isolated test"},
                    status="PENDING",
                    attempt_count=0,
                    next_attempt_at=now - timedelta(seconds=1),
                    created_at=now,
                    updated_at=now,
                )
            )
        async with sessions() as session:
            claim = await claim_next_notification(session)
        assert claim is not None
        async with sessions() as session:
            await record_notification_outcome(
                session,
                claim.notification_id,
                NotificationOutcome(
                    claim_token=claim.claim_token,
                    kind=NotificationOutcomeKind.DELIVERED,
                ),
            )
        after_detail, after_etag = await _get_detail_etag(client, case.order_id)
        assert after_etag == before_etag
        assert after_detail["order"]["state"] == before_detail["order"]["state"]
        assert len(after_detail["revisions"]) == len(before_detail["revisions"])
        async with sessions() as session:
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.order_id == case.order_id)
            )
            revision_count = await session.scalar(
                select(func.count())
                .select_from(ReviewRevisionModel)
                .where(ReviewRevisionModel.order_id == case.order_id)
            )
        assert audit_count == before_audit_count
        assert revision_count == len(before_detail["revisions"])
