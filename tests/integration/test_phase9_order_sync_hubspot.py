"""M9D adapter behavior through the durable M9B coordinator and PostgreSQL."""

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from opsflow.application.order_sync import execute_next_order_sync
from opsflow.domain import OrderState
from opsflow.hubspot import HUBSPOT_COMPANY_IDENTITY, HUBSPOT_DEAL_IDENTITY, HubSpotCRMAdapter
from opsflow.order_sync.contracts import (
    ExecuteNextKind,
    OdooOrderReceipt,
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepFailure,
)
from opsflow.order_sync.executor import Phase9OrderSyncExecutor
from opsflow.persistence.models import (
    AuditEventModel,
    OrderLineModel,
    OrderModel,
    OrderSyncModel,
)
from opsflow.review.composition import build_demo_review_runtime
from opsflow.settings import Settings

_ROOT = Path(__file__).parents[2]
_SERVICE_KEY_SENTINEL = "HUBSPOT_SERVICE_KEY_DO_NOT_LEAK"
_SYNTHETIC_PROVIDER_BODY = (
    "HUBSPOT_BODY_DO_NOT_LEAK HUBSPOT_TRACEBACK_DO_NOT_LEAK SYNTHETIC_CRM_PAYLOAD_DO_NOT_LEAK"
)


def test_hubspot_receipts_resume_at_first_missing_step_without_repeating_odoo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(_assert_receipt_boundaries_and_resume(caplog))


def test_lost_hubspot_response_replays_same_identity_and_persists_receipt() -> None:
    asyncio.run(_assert_lost_company_response_replays_same_identity())


def test_lost_hubspot_deal_response_replays_same_identity_and_persists_receipt() -> None:
    asyncio.run(_assert_lost_deal_response_replays_same_identity())


def test_missing_hubspot_configuration_returns_503_before_claim() -> None:
    asyncio.run(_assert_missing_hubspot_settings_fail_closed())


def test_two_hubspot_requests_share_one_m9b_step_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(_assert_two_hubspot_requests_share_one_step_allowance(monkeypatch))


def test_hubspot_diagnostics_do_not_leak_through_execute_api(
    caplog: pytest.LogCaptureFixture,
) -> None:
    asyncio.run(_assert_hubspot_diagnostics_do_not_leak_through_execute_api(caplog))


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url=database_url,
        hubspot_service_key=_SERVICE_KEY_SENTINEL,
        hubspot_pipeline_id="default",
        hubspot_initial_stage_id="appointmentscheduled",
        hubspot_portal_currency="USD",
        hubspot_expected_portal_id=149461984,
    )


class _TrackingSessionMaker:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self.maker = maker
        self.sessions: list[AsyncSession] = []

    def __call__(self) -> AsyncSession:
        session = self.maker()
        self.sessions.append(session)
        return session


class _OdooStepFake:
    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        self.calls: list[OrderSyncStep] = []

    async def execute(self, order_id: UUID, step: OrderSyncStep):
        assert order_id == self.order_id
        self.calls.append(step)
        if step is OrderSyncStep.ODOO_LOOKUP:
            return None
        if step is OrderSyncStep.ODOO_BRIDGE:
            return OdooOrderReceipt(9001, "S009001")
        return OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)


class _HubSpotTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        sessions: _TrackingSessionMaker,
        *,
        order_id: UUID,
        checkpoint_sessions: async_sessionmaker[AsyncSession],
        fail_deal_once: bool = False,
        fail_association_once: bool = False,
        lose_first_company_response: bool = False,
        lose_first_deal_response: bool = False,
        delay_seconds: float = 0,
    ) -> None:
        self.sessions = sessions
        self.order_id = order_id
        self.checkpoint_sessions = checkpoint_sessions
        self.fail_deal_once = fail_deal_once
        self.fail_association_once = fail_association_once
        self.lose_first_company_response = lose_first_company_response
        self.lose_first_deal_response = lose_first_deal_response
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[str, str, object | None]] = []
        self.company_ids: dict[str, str] = {}
        self.deal_ids: dict[str, str] = {}
        self.company_upserts = 0
        self.deal_upserts = 0
        self.association_puts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        assert not any(session.in_transaction() for session in self.sessions.sessions)
        async with self.checkpoint_sessions() as session:
            sync = await session.get(OrderSyncModel, self.order_id)
            assert sync is not None and sync.in_flight_step is not None
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        if request.url.path == "/integrations/v1/me":
            return httpx.Response(200, json={"portalId": 149461984}, request=request)
        if request.url.path.endswith("/companies/batch/upsert"):
            self.company_upserts += 1
            item = body["inputs"][0]
            reference = item["id"]
            company_id = self.company_ids.setdefault(reference, "company-synthetic-9001")
            if self.lose_first_company_response:
                self.lose_first_company_response = False
                raise httpx.ReadTimeout(_SYNTHETIC_PROVIDER_BODY, request=request)
            return _upsert_response(request, item, company_id, HUBSPOT_COMPANY_IDENTITY, reference)
        if request.url.path.endswith("/0-3/search"):
            return httpx.Response(200, json={"total": 0, "results": []}, request=request)
        if request.url.path.endswith("/0-3/batch/upsert"):
            self.deal_upserts += 1
            if self.fail_deal_once:
                self.fail_deal_once = False
                return httpx.Response(500, text=_SYNTHETIC_PROVIDER_BODY, request=request)
            item = body["inputs"][0]
            identity = item["id"]
            deal_id = self.deal_ids.setdefault(identity, "deal-synthetic-9001")
            if self.lose_first_deal_response:
                self.lose_first_deal_response = False
                raise httpx.ReadTimeout(_SYNTHETIC_PROVIDER_BODY, request=request)
            return _upsert_response(request, item, deal_id, HUBSPOT_DEAL_IDENTITY, identity)
        if request.method == "PUT" and "/associations/default/company/" in request.url.path:
            self.association_puts += 1
            if self.fail_association_once:
                self.fail_association_once = False
                return httpx.Response(500, text=_SYNTHETIC_PROVIDER_BODY, request=request)
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETE",
                    "results": [
                        {
                            "from": {"id": "deal-synthetic-9001"},
                            "to": {"id": "company-synthetic-9001"},
                            "associationSpec": {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": 341,
                            },
                        }
                    ],
                },
                request=request,
            )
        if request.method == "GET" and request.url.path.endswith("/associations/company"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "toObjectId": "company-synthetic-9001",
                            "associationTypes": [{"typeId": 341}, {"typeId": 5}],
                        }
                    ]
                },
                request=request,
            )
        raise AssertionError(f"unexpected fake HubSpot route {request.method} {request.url.path}")


def _upsert_response(
    request: httpx.Request,
    item: dict[str, object],
    provider_id: str,
    identity_property: str,
    identity: str,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "COMPLETE",
            "results": [
                {
                    "id": provider_id,
                    "properties": {identity_property: identity},
                    "objectWriteTraceId": item["objectWriteTraceId"],
                }
            ],
            "errors": [],
        },
        request=request,
    )


async def _new_state() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID]:
    _run_alembic("upgrade", "head")
    engine = create_async_engine(Settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    order_id = uuid4()
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        session.add(
            OrderModel(
                id=order_id,
                customer_reference="CUST-001",
                po_number="PO-M9D-SYNTHETIC",
                order_date=None,
                requested_delivery_date=None,
                currency="USD",
                state=OrderState.APPROVED.value,
                failure_origin=None,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            OrderLineModel(
                id=uuid4(),
                order_id=order_id,
                position=0,
                sku="SKU-001",
                description="Synthetic approved line",
                quantity=Decimal("2"),
                submitted_price=Decimal("10.25"),
                trusted_catalogue_price=Decimal("10"),
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
                odoo_sale_order_id=None,
                odoo_sale_order_name=None,
                hubspot_company_id=None,
                hubspot_deal_id=None,
                hubspot_association_confirmed_at=None,
                in_flight_step=None,
                last_failure_step=None,
                last_failure_code=None,
                last_attempt_at=None,
                created_at=now,
                updated_at=now,
            )
        )
    return engine, sessions, order_id


def _adapter(
    sessions: _TrackingSessionMaker,
    transport: _HubSpotTransport,
    database_url: str,
) -> HubSpotCRMAdapter:
    return HubSpotCRMAdapter(
        _settings(database_url),
        sessionmaker=sessions,
        business_data_provider=build_demo_review_runtime().provider,
        transport=transport,
    )


async def _assert_receipt_boundaries_and_resume(caplog: pytest.LogCaptureFixture) -> None:
    engine, base_sessions, order_id = await _new_state()
    tracking = _TrackingSessionMaker(base_sessions)
    transport = _HubSpotTransport(
        tracking,
        order_id=order_id,
        checkpoint_sessions=base_sessions,
        fail_deal_once=True,
        fail_association_once=True,
    )
    hubspot = _adapter(tracking, transport, Settings().database_url)
    odoo = _OdooStepFake(order_id)
    executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=hubspot)
    coordinator_session = base_sessions()
    tracking.sessions.append(coordinator_session)
    try:
        first = await execute_next_order_sync(coordinator_session, executor)
        assert first.kind is ExecuteNextKind.RETRY_WAIT
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.odoo_sale_order_id == 9001
        assert sync.hubspot_company_id == "company-synthetic-9001"
        assert sync.hubspot_deal_id is None
        assert sync.in_flight_step == OrderSyncStep.HUBSPOT_DEAL.value
        assert transport.company_upserts == 1 and transport.deal_upserts == 1

        await _make_eligible(base_sessions, order_id)
        second_session = base_sessions()
        tracking.sessions.append(second_session)
        second = await execute_next_order_sync(second_session, executor)
        await second_session.close()
        assert second.kind is ExecuteNextKind.RETRY_WAIT
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.hubspot_company_id == "company-synthetic-9001"
        assert sync.hubspot_deal_id == "deal-synthetic-9001"
        assert sync.hubspot_association_confirmed_at is None
        assert sync.in_flight_step == OrderSyncStep.HUBSPOT_ASSOCIATION.value
        assert transport.company_upserts == 1 and transport.deal_upserts == 2
        assert transport.association_puts == 1

        await _make_eligible(base_sessions, order_id)
        third_session = base_sessions()
        tracking.sessions.append(third_session)
        third = await execute_next_order_sync(third_session, executor)
        await third_session.close()
        assert third.kind is ExecuteNextKind.COMPLETED
        assert transport.company_upserts == 1 and transport.deal_upserts == 2
        assert transport.association_puts == 2
        assert odoo.calls == [OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE]
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            events = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
        assert sync is not None and sync.hubspot_association_confirmed_at is not None
        assert sync.odoo_sale_order_id == 9001
        assert sync.hubspot_company_id == "company-synthetic-9001"
        assert sync.hubspot_deal_id == "deal-synthetic-9001"
        assert _SYNTHETIC_PROVIDER_BODY not in repr(sync)
        assert _SYNTHETIC_PROVIDER_BODY not in repr(events)
        assert _SYNTHETIC_PROVIDER_BODY not in caplog.text
    finally:
        await coordinator_session.close()
        await hubspot.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_lost_company_response_replays_same_identity() -> None:
    engine, base_sessions, order_id = await _new_state()
    tracking = _TrackingSessionMaker(base_sessions)
    transport = _HubSpotTransport(
        tracking,
        order_id=order_id,
        checkpoint_sessions=base_sessions,
        lose_first_company_response=True,
    )
    hubspot = _adapter(tracking, transport, Settings().database_url)
    odoo = _OdooStepFake(order_id)
    executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=hubspot)
    first_session = base_sessions()
    tracking.sessions.append(first_session)
    try:
        first = await execute_next_order_sync(first_session, executor)
        assert first.kind is ExecuteNextKind.RETRY_WAIT
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None and sync.hubspot_company_id is None
        assert sync.in_flight_step == OrderSyncStep.HUBSPOT_COMPANY.value
        await _make_eligible(base_sessions, order_id)
        second_session = base_sessions()
        tracking.sessions.append(second_session)
        second = await execute_next_order_sync(second_session, executor)
        await second_session.close()
        assert second.kind is ExecuteNextKind.COMPLETED
        assert transport.company_upserts == 2
        assert transport.company_ids == {"CUST-001": "company-synthetic-9001"}
        assert odoo.calls == [OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE]
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None and sync.hubspot_company_id == "company-synthetic-9001"
        assert sync.hubspot_deal_id == "deal-synthetic-9001"
        assert sync.hubspot_association_confirmed_at is not None
    finally:
        await first_session.close()
        await hubspot.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_lost_deal_response_replays_same_identity() -> None:
    engine, base_sessions, order_id = await _new_state()
    tracking = _TrackingSessionMaker(base_sessions)
    transport = _HubSpotTransport(
        tracking,
        order_id=order_id,
        checkpoint_sessions=base_sessions,
        lose_first_deal_response=True,
    )
    hubspot = _adapter(tracking, transport, Settings().database_url)
    odoo = _OdooStepFake(order_id)
    executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=hubspot)
    first_session = base_sessions()
    tracking.sessions.append(first_session)
    try:
        first = await execute_next_order_sync(first_session, executor)
        assert first.kind is ExecuteNextKind.RETRY_WAIT
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.hubspot_company_id == "company-synthetic-9001"
        assert sync.hubspot_deal_id is None
        assert sync.in_flight_step == OrderSyncStep.HUBSPOT_DEAL.value

        await _make_eligible(base_sessions, order_id)
        second_session = base_sessions()
        tracking.sessions.append(second_session)
        second = await execute_next_order_sync(second_session, executor)
        await second_session.close()
        assert second.kind is ExecuteNextKind.COMPLETED
        assert transport.company_upserts == 1
        assert transport.deal_upserts == 2
        assert transport.deal_ids == {str(order_id): "deal-synthetic-9001"}
        assert odoo.calls == [OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE]
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.hubspot_deal_id == "deal-synthetic-9001"
        assert sync.hubspot_association_confirmed_at is not None
    finally:
        await first_session.close()
        await hubspot.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_missing_hubspot_settings_fail_closed() -> None:
    engine, base_sessions, order_id = await _new_state()
    # Odoo-only app composition intentionally has no Phase 9 executor.
    from opsflow.main import create_app

    app_settings = Settings(
        _env_file=None,
        database_url=Settings().database_url,
        odoo_base_url="http://odoo.test",
        odoo_database="synthetic-m9d",
        odoo_api_key="synthetic-odoo-key",
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
        orchestration_token="synthetic-m9d-orchestration-token",
    )
    app = create_app(app_settings)
    try:
        assert app.state.order_sync_step_executor is None
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(
                "/v1/orchestration/order-sync/execute-next",
                headers={"Authorization": "Bearer synthetic-m9d-orchestration-token"},
            )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "ORDER_SYNC_UNAVAILABLE"
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
        assert sync is not None and sync.claim_token is None
        assert order is not None and order.state == OrderState.APPROVED.value
    finally:
        await app.state.database_engine.dispose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_two_hubspot_requests_share_one_step_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opsflow.application.order_sync as order_sync

    engine, base_sessions, order_id = await _new_state()
    tracking = _TrackingSessionMaker(base_sessions)
    transport = _HubSpotTransport(
        tracking,
        order_id=order_id,
        checkpoint_sessions=base_sessions,
        delay_seconds=0.08,
    )
    hubspot = _adapter(tracking, transport, Settings().database_url)
    odoo = _OdooStepFake(order_id)
    executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=hubspot)
    coordinator_session = base_sessions()
    tracking.sessions.append(coordinator_session)
    monkeypatch.setitem(
        order_sync._STEP_TIMEOUTS,
        OrderSyncStep.HUBSPOT_COMPANY,
        timedelta(milliseconds=120),
    )
    started = time.monotonic()
    try:
        result = await execute_next_order_sync(coordinator_session, executor)
        elapsed = time.monotonic() - started
        assert result.kind is ExecuteNextKind.RETRY_WAIT
        assert elapsed < 0.5
        assert transport.company_upserts == 0
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.odoo_sale_order_id == 9001
        assert sync.hubspot_company_id is None
        assert sync.in_flight_step == OrderSyncStep.HUBSPOT_COMPANY.value
        assert sync.last_failure_code == OrderSyncFailureCode.PROVIDER_UNAVAILABLE.value
    finally:
        await coordinator_session.close()
        await hubspot.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_hubspot_diagnostics_do_not_leak_through_execute_api(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine, base_sessions, order_id = await _new_state()
    tracking = _TrackingSessionMaker(base_sessions)
    transport = _HubSpotTransport(
        tracking,
        order_id=order_id,
        checkpoint_sessions=base_sessions,
        fail_deal_once=True,
    )
    hubspot = _adapter(tracking, transport, Settings().database_url)
    odoo = _OdooStepFake(order_id)

    from opsflow.main import create_app

    app = create_app(
        Settings(
            _env_file=None,
            database_url=Settings().database_url,
            orchestration_token="synthetic-m9d-api-token",
        )
    )
    app.state.hubspot_adapter = hubspot
    app.state.order_sync_step_executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=hubspot)
    caplog.clear()
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(
                "/v1/orchestration/order-sync/execute-next",
                headers={"Authorization": "Bearer synthetic-m9d-api-token"},
            )
        assert response.status_code == 200
        assert response.json()["result"] == "retry_wait"
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            events = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
        assert sync is not None
        assert sync.last_failure_code == OrderSyncFailureCode.PROVIDER_UNAVAILABLE.value
        assert sync.hubspot_company_id == "company-synthetic-9001"
        assert sync.hubspot_deal_id is None
        sinks = (response.text, repr(sync), repr(events), caplog.text)
        for sentinel in (
            _SERVICE_KEY_SENTINEL,
            "HUBSPOT_BODY_DO_NOT_LEAK",
            "HUBSPOT_TRACEBACK_DO_NOT_LEAK",
            "SYNTHETIC_CRM_PAYLOAD_DO_NOT_LEAK",
        ):
            assert all(sentinel not in sink for sink in sinks)
    finally:
        await app.state.database_engine.dispose()
        await _dispose(engine, base_sessions, order_id)


async def _make_eligible(sessions: async_sessionmaker[AsyncSession], order_id: UUID) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            update(OrderSyncModel)
            .where(OrderSyncModel.order_id == order_id)
            .values(next_attempt_at=func.now() - timedelta(seconds=1))
        )


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
        cwd=_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
