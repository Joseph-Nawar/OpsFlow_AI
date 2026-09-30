"""Authenticated execute-next route tests using deterministic provider-free fakes."""

import asyncio
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from opsflow.domain import OrderState
from opsflow.main import create_app
from opsflow.order_sync.contracts import (
    HubSpotAssociationReceipt,
    HubSpotCompanyReceipt,
    HubSpotDealReceipt,
    OdooOrderReceipt,
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepFailure,
)
from opsflow.persistence.models import AuditEventModel, OrderModel, OrderSyncModel
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

SERVICE_TOKEN = "synthetic-phase9-sync-service-token"
REVIEW_TOKEN = "synthetic-phase9-review-token"
AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
EXECUTE_PATH = "/v1/orchestration/order-sync/execute-next"
REPOSITORY_ROOT = Path(__file__).parents[2]
_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def test_execute_next_route_is_registered() -> None:
    paths = create_app(_settings()).openapi()["paths"]
    assert EXECUTE_PATH in paths
    response = paths[EXECUTE_PATH]["post"]["responses"]
    assert {"200", "401", "503"} <= set(response)


def test_execute_next_requires_service_authentication() -> None:
    asyncio.run(_assert_authentication())


def test_missing_executor_returns_503_without_claiming() -> None:
    asyncio.run(_assert_missing_executor_does_not_claim())


def test_execute_next_with_fake_executor_claims_and_records_receipt() -> None:
    asyncio.run(_assert_fake_executor_completes_through_coordinator())


def test_execute_next_resumes_at_company_after_odoo_receipt_and_hubspot_failure() -> None:
    asyncio.run(_assert_company_resume_after_hubspot_failure())


def test_budget_yield_after_receipt_keeps_attempt_count() -> None:
    asyncio.run(_assert_budget_yield_after_receipt())


def test_execute_next_deadline_bounds_delayed_claim_and_rolls_back() -> None:
    asyncio.run(_assert_delayed_claim_obeys_total_deadline())


def test_completed_order_is_not_executed_again() -> None:
    asyncio.run(_assert_completed_order_is_not_reexecuted())


def test_lease_exhaustion_is_reported_and_empty_invocation_is_no_work() -> None:
    asyncio.run(_assert_lease_exhaustion_result_is_reported())


def test_parallel_execute_next_requests_have_one_owner() -> None:
    asyncio.run(_assert_parallel_requests_have_one_owner())


def _settings() -> Settings:
    return Settings(
        orchestration_token=SERVICE_TOKEN,
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=REVIEW_TOKEN,
                actor="phase9-review-test",
                role=OperatorRole.REVIEWER,
            ),
        ),
    )


async def _assert_authentication() -> None:
    app = create_app(_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        responses = (
            await client.post(EXECUTE_PATH),
            await client.post(EXECUTE_PATH, headers={"Authorization": "Bearer wrong"}),
            await client.post(EXECUTE_PATH, headers={"Authorization": f"Bearer {REVIEW_TOKEN}"}),
        )
    for response in responses:
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "ORCHESTRATION_UNAUTHENTICATED"
    assert SERVICE_TOKEN not in "".join(response.text for response in responses)
    assert REVIEW_TOKEN not in responses[2].text


async def _assert_missing_executor_does_not_claim() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(EXECUTE_PATH, headers=AUTH)
        assert response.status_code == 503
        assert response.json() == {
            "detail": {
                "code": "ORDER_SYNC_UNAVAILABLE",
                "message": "Order synchronization is currently unavailable.",
            }
        }
        async with sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
            events = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
        assert sync is not None and sync.claim_token is None
        assert order is not None and order.state == OrderState.APPROVED.value
        assert events == ()
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_fake_executor_completes_through_coordinator() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    fake = FakeExecutor()
    app.state.order_sync_step_executor = fake
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(EXECUTE_PATH, headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "result": "completed",
            "order_id": str(order_id),
            "state": "COMPLETED",
        }
        assert fake.calls == [
            OrderSyncStep.ODOO_LOOKUP,
            OrderSyncStep.ODOO_BRIDGE,
            OrderSyncStep.HUBSPOT_COMPANY,
            OrderSyncStep.HUBSPOT_DEAL,
            OrderSyncStep.HUBSPOT_ASSOCIATION,
        ]
        async with sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
        assert sync is not None
        assert sync.odoo_sale_order_id == 9001
        assert sync.hubspot_company_id == "company-9001"
        assert sync.hubspot_deal_id == "deal-9001"
        assert sync.hubspot_association_confirmed_at is not None
        assert order is not None and order.state == OrderState.COMPLETED.value
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_company_resume_after_hubspot_failure() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    fake = FakeExecutor(fail_company_once=True)
    app.state.order_sync_step_executor = fake
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            first = await client.post(EXECUTE_PATH, headers=AUTH)
            assert first.status_code == 200, first.text
            async with sessions() as session, session.begin():
                await session.execute(
                    update(OrderSyncModel)
                    .where(OrderSyncModel.order_id == order_id)
                    .values(next_attempt_at=func.now() - timedelta(seconds=1))
                )
            second = await client.post(EXECUTE_PATH, headers=AUTH)
        assert first.json()["result"] == "retry_wait"
        assert first.json()["state"] == "SYNCING"
        assert second.json()["result"] == "completed"
        assert fake.calls == [
            OrderSyncStep.ODOO_LOOKUP,
            OrderSyncStep.ODOO_BRIDGE,
            OrderSyncStep.HUBSPOT_COMPANY,
            OrderSyncStep.HUBSPOT_COMPANY,
            OrderSyncStep.HUBSPOT_DEAL,
            OrderSyncStep.HUBSPOT_ASSOCIATION,
        ]
        async with sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
        assert sync is not None and sync.attempt_count == 1
        assert sync.odoo_sale_order_id == 9001
        assert order is not None and order.state == OrderState.COMPLETED.value
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_budget_yield_after_receipt() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    clock = [0.0]
    fake = BudgetAdvancingExecutor(clock)
    app.state.order_sync_step_executor = fake
    import opsflow.application.order_sync as order_sync_application

    original_monotonic = order_sync_application._monotonic
    order_sync_application._monotonic = lambda: clock[0]
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(EXECUTE_PATH, headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json()["result"] == "yielded"
        assert response.json()["state"] == "SYNCING"
        assert fake.calls == [OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE]
        async with sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.odoo_sale_order_id == 9001
        assert sync.attempt_count == 0
        assert sync.claim_token is None and sync.claim_expires_at is None
        assert sync.in_flight_step is None
    finally:
        order_sync_application._monotonic = original_monotonic
        await _dispose(engine, sessions, order_id)


async def _assert_delayed_claim_obeys_total_deadline() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    fake = FakeExecutor()
    app.state.order_sync_step_executor = fake
    import opsflow.application.order_sync as order_sync_application

    original_claim = order_sync_application.claim_one_eligible_order_sync
    original_defaults = order_sync_application.execute_next_order_sync.__kwdefaults__
    test_budget = timedelta(milliseconds=75)

    async def delayed_claim(session: AsyncSession):
        await session.execute(text("SELECT pg_sleep(0.5)"))
        return await original_claim(session)

    order_sync_application.execute_next_order_sync.__kwdefaults__ = {
        **(original_defaults or {}),
        "execution_budget": test_budget,
    }
    order_sync_application.claim_one_eligible_order_sync = delayed_claim
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            started = time.monotonic()
            response = await client.post(EXECUTE_PATH, headers=AUTH)
            elapsed = time.monotonic() - started
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "ORDER_SYNC_UNAVAILABLE"
        assert elapsed < 0.4
        assert fake.calls == []
        async with sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
            events = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
            assert await session.scalar(text("SELECT 1")) == 1
        assert sync is not None and sync.claim_token is None
        assert order is not None and order.state == OrderState.APPROVED.value
        assert events == ()
    finally:
        order_sync_application.claim_one_eligible_order_sync = original_claim
        order_sync_application.execute_next_order_sync.__kwdefaults__ = original_defaults
        await _dispose(engine, sessions, order_id)


async def _assert_completed_order_is_not_reexecuted() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    fake = FakeExecutor()
    app.state.order_sync_step_executor = fake
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            first = await client.post(EXECUTE_PATH, headers=AUTH)
            second = await client.post(EXECUTE_PATH, headers=AUTH)
        assert first.json()["result"] == "completed"
        assert second.json() == {"result": "no_work", "order_id": None, "state": None}
        assert len(fake.calls) == 5
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_lease_exhaustion_result_is_reported() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    fake = FakeExecutor()
    app.state.order_sync_step_executor = fake
    async with sessions() as session, session.begin():
        order = await session.get(OrderModel, order_id)
        sync = await session.get(OrderSyncModel, order_id)
        assert order is not None and sync is not None
        order.state = OrderState.SYNCING.value
        sync.attempt_count = 2
        sync.claim_token = uuid4()
        sync.claim_expires_at = func.clock_timestamp() - text("interval '1 second'")
        sync.in_flight_step = OrderSyncStep.ODOO_LOOKUP.value
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            exhausted = await client.post(EXECUTE_PATH, headers=AUTH)
            empty = await client.post(EXECUTE_PATH, headers=AUTH)
        assert exhausted.status_code == 200
        assert exhausted.json() == {
            "result": "needs_review",
            "order_id": str(order_id),
            "state": "FAILED_RETRYABLE",
        }
        assert empty.status_code == 200
        assert empty.json() == {"result": "no_work", "order_id": None, "state": None}
        assert fake.calls == []
        async with sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
        assert sync is not None
        assert sync.attempt_count == 3
        assert sync.last_failure_code == OrderSyncFailureCode.WORKER_LEASE_EXHAUSTED.value
        assert sync.claim_token is None and sync.claim_expires_at is None
        assert order is not None and order.state == OrderState.FAILED_RETRYABLE.value
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_parallel_requests_have_one_owner() -> None:
    engine, sessions, order_id = await _seed_order()
    app = create_app(_settings())
    fake = GatedExecutor()
    app.state.order_sync_step_executor = fake
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            first_task = asyncio.create_task(client.post(EXECUTE_PATH, headers=AUTH))
            await fake.started.wait()
            second = await client.post(EXECUTE_PATH, headers=AUTH)
            fake.release.set()
            first = await first_task
        assert first.status_code == 200 and first.json()["result"] == "completed"
        assert second.status_code == 200 and second.json()["result"] == "no_work"
        assert len(fake.calls) == 5
        async with sessions() as session:
            order = await session.get(OrderModel, order_id)
        assert order is not None and order.state == OrderState.COMPLETED.value
    finally:
        fake.release.set()
        await _dispose(engine, sessions, order_id)


class FakeExecutor:
    def __init__(self, *, fail_company_once: bool = False) -> None:
        self.calls: list[OrderSyncStep] = []
        self.fail_company_once = fail_company_once

    async def execute(self, order_id: UUID, step: OrderSyncStep):
        del order_id
        self.calls.append(step)
        if step is OrderSyncStep.HUBSPOT_COMPANY and self.fail_company_once:
            self.fail_company_once = False
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        if step is OrderSyncStep.ODOO_LOOKUP:
            return None
        if step is OrderSyncStep.ODOO_BRIDGE:
            return OdooOrderReceipt(9001, "S009001")
        if step is OrderSyncStep.HUBSPOT_COMPANY:
            return HubSpotCompanyReceipt("company-9001")
        if step is OrderSyncStep.HUBSPOT_DEAL:
            return HubSpotDealReceipt("deal-9001")
        if step is OrderSyncStep.HUBSPOT_ASSOCIATION:
            return HubSpotAssociationReceipt(datetime.now(UTC))
        raise AssertionError(f"unexpected step: {step}")


class BudgetAdvancingExecutor(FakeExecutor):
    def __init__(self, clock: list[float]) -> None:
        super().__init__()
        self.clock = clock

    async def execute(self, order_id: UUID, step: OrderSyncStep):
        result = await super().execute(order_id, step)
        if step is OrderSyncStep.ODOO_BRIDGE:
            # Model a confirmed external success that returns with one second left.
            self.clock[0] = 209.0
        return result


class GatedExecutor(FakeExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, order_id: UUID, step: OrderSyncStep):
        if not self.started.is_set():
            self.started.set()
            await self.release.wait()
        return await super().execute(order_id, step)


async def _seed_order() -> tuple[object, async_sessionmaker[AsyncSession], UUID]:
    _run_alembic("upgrade", "head")
    engine = create_async_engine(Settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    order_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(OrderModel(id=order_id, state=OrderState.APPROVED.value, created_at=_NOW))
        session.add(
            OrderSyncModel(
                order_id=order_id,
                claim_token=None,
                claim_expires_at=None,
                attempt_count=0,
                retry_generation=0,
                next_attempt_at=datetime(1970, 1, 1, tzinfo=UTC),
                odoo_sale_order_id=None,
                odoo_sale_order_name=None,
                hubspot_company_id=None,
                hubspot_deal_id=None,
                hubspot_association_confirmed_at=None,
                in_flight_step=None,
                last_failure_step=None,
                last_failure_code=None,
                last_attempt_at=None,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
    return engine, sessions, order_id


async def _dispose(
    engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    order_id: UUID,
) -> None:
    async with sessions() as session, session.begin():
        await session.execute(delete(OrderModel).where(OrderModel.id == order_id))
    await engine.dispose()


def _run_alembic(*arguments: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=REPOSITORY_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
