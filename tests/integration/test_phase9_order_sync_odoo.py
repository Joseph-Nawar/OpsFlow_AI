"""M9B coordinator tests with Odoo JSON-2 replaced by deterministic HTTP doubles."""

import asyncio
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from opsflow.application.order_sync import execute_next_order_sync
from opsflow.domain import OrderState
from opsflow.main import create_app
from opsflow.odoo import OdooERPAdapter
from opsflow.order_sync.contracts import (
    ExecuteNextKind,
    OrderSyncFailureCode,
    OrderSyncStep,
)
from opsflow.persistence.models import AuditEventModel, OrderLineModel, OrderModel, OrderSyncModel
from opsflow.review.composition import build_demo_review_runtime
from opsflow.settings import Settings
from opsflow.validation.policy import ValidationPolicy

_ROOT = Path(__file__).parents[2]
_RESPONSE_SENTINEL = "ODOO_RESPONSE_BODY_SENTINEL_DO_NOT_LEAK"
_TRACEBACK_SENTINEL = "ODOO_TRACEBACK_DEBUG_SENTINEL_DO_NOT_LEAK"
_API_KEY_SENTINEL = "ODOO_API_KEY_SENTINEL_DO_NOT_LEAK"
_SENTINEL = f"{_RESPONSE_SENTINEL} {_TRACEBACK_SENTINEL} {_API_KEY_SENTINEL}"
_SERVICE_TOKEN = "m9c-api-test-service-token"
_AUTH = {"Authorization": f"Bearer {_SERVICE_TOKEN}"}
_EXECUTE_PATH = "/v1/orchestration/order-sync/execute-next"


def test_odoo_receipt_is_durable_through_existing_execute_next_coordinator() -> None:
    asyncio.run(_assert_receipt_persists_before_crm_step())


def test_odoo_timeout_after_possible_commit_replays_same_opsflow_identity() -> None:
    asyncio.run(_assert_lost_response_replays_same_identity())


def test_bridge_resume_preflights_current_price_before_new_remote_order() -> None:
    asyncio.run(_assert_bridge_preflights_current_price_for_new_order())


def test_executor_runs_with_no_open_opsflow_transaction() -> None:
    asyncio.run(_assert_executor_runs_without_open_transactions())


def test_multi_call_odoo_executor_is_bounded_by_m9b_step_allowance() -> None:
    asyncio.run(_assert_multi_call_executor_obeys_m9b_allowance())


def test_odoo_diagnostics_never_leak_to_persisted_failure_or_audit() -> None:
    asyncio.run(_assert_provider_details_are_not_persisted())


def test_odoo_diagnostics_never_leak_to_api_logs_or_persistence(caplog) -> None:
    asyncio.run(_assert_provider_details_are_not_exposed(caplog))


def _runtime_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url=database_url,
        odoo_base_url="http://odoo.test",
        odoo_database="opsflow_disposable_test",
        odoo_api_key=_API_KEY_SENTINEL,
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
    )


def _runtime_policy() -> ValidationPolicy:
    return build_demo_review_runtime().policy


class _TrackingSessionMaker:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker
        self.sessions: list[AsyncSession] = []

    def __call__(self) -> AsyncSession:
        session = self._maker()
        self.sessions.append(session)
        return session


class _OdooFake(httpx.AsyncBaseTransport):
    def __init__(
        self,
        sessions: _TrackingSessionMaker | None = None,
        *,
        checkpoint_sessionmaker=None,
        checkpoint_order_id=None,
    ) -> None:
        self.sessions = sessions
        self.checkpoint_sessionmaker = checkpoint_sessionmaker
        self.checkpoint_order_id = checkpoint_order_id
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.requests_started = 0
        self.bridge_calls: list[dict[str, object]] = []
        self.receipts: dict[str, tuple[int, str]] = {}
        self.lose_first_bridge_response = False
        self.delay_seconds = 0.0
        self.cancelled = False
        self.fail_next_bridge = False
        self.assert_no_transaction_on_request = False
        self.change_product_price_after_request_count: int | None = None
        self.remove_stock_after_request_count: int | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests_started += 1
        if self.assert_no_transaction_on_request and self.sessions is not None:
            assert not any(session.in_transaction() for session in self.sessions.sessions)
        if self.checkpoint_sessionmaker is not None:
            async with self.checkpoint_sessionmaker() as session:
                sync = await session.get(OrderSyncModel, self.checkpoint_order_id)
                in_flight_step = None if sync is None else sync.in_flight_step
            assert in_flight_step in (
                OrderSyncStep.ODOO_LOOKUP.value,
                OrderSyncStep.ODOO_BRIDGE.value,
            )
        if self.delay_seconds:
            try:
                await asyncio.sleep(self.delay_seconds)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        payloads: dict[str, object] = {
            "/json/2/res.company/read": [{"id": 1, "currency_id": [10, "USD"], "active": True}],
            "/json/2/stock.warehouse/read": [
                {"id": 2, "company_id": [1, "OpsFlow Demo"], "lot_stock_id": [9, "Stock"]}
            ],
            "/json/2/product.pricelist/read": [
                {"id": 3, "company_id": [1, "OpsFlow Demo"], "currency_id": [10, "USD"]}
            ],
            "/json/2/res.currency/read": [
                {"id": 10, "name": "USD", "active": True, "rounding": 0.01}
            ],
            "/json/2/product.pricelist.item/search_count": 0,
            "/json/2/res.partner/search_read": [
                {
                    "id": 20,
                    "ref": "CUST-001",
                    "name": "Synthetic Customer",
                    "active": True,
                    "is_company": True,
                    "customer_rank": 1,
                    "company_id": False,
                }
            ],
            "/json/2/product.product/search_read": [
                {
                    "id": 30,
                    "default_code": "SKU-001",
                    "name": "Synthetic Product",
                    "active": True,
                    "sale_ok": True,
                    "is_storable": True,
                    "uom_id": [40, "Units"],
                    "currency_id": [10, "USD"],
                    "product_tmpl_id": [50, "Synthetic Template"],
                    "lst_price": 10.0,
                    "free_qty": 8.0,
                }
            ],
        }
        if request.url.path == "/json/2/sale.order/opsflow_create_or_get_sale_order":
            self.bridge_calls.append(body)
            order_id = str(body["opsflow_order_id"])
            if order_id not in self.receipts:
                self.receipts[order_id] = (9001, "S009001")
                if self.lose_first_bridge_response:
                    self.lose_first_bridge_response = False
                    return httpx.Response(503, text=_SENTINEL, request=request)
                outcome = "created"
            else:
                outcome = "replayed"
            sale_order_id, sale_order_name = self.receipts[order_id]
            return httpx.Response(
                200,
                json={
                    "outcome": outcome,
                    "opsflow_order_id": order_id,
                    "sale_order_id": sale_order_id,
                    "sale_order_name": sale_order_name,
                    "confirmed_state": "sale",
                },
                request=request,
            )
        if request.url.path == "/json/2/sale.order/search_read":
            order_id = body["domain"][0][2]
            receipt = self.receipts.get(order_id)
            records = [] if receipt is None else [{"id": receipt[0], "opsflow_order_id": order_id}]
            return httpx.Response(200, json=records, request=request)
        payload = payloads.get(request.url.path)
        if (
            request.url.path == "/json/2/product.product/search_read"
            and self.change_product_price_after_request_count is not None
            and self.requests_started > self.change_product_price_after_request_count
        ):
            assert isinstance(payload, list) and len(payload) == 1
            payload = [{**payload[0], "lst_price": 100.0}]
        if (
            request.url.path == "/json/2/product.product/search_read"
            and self.remove_stock_after_request_count is not None
            and self.requests_started > self.remove_stock_after_request_count
        ):
            assert isinstance(payload, list) and len(payload) == 1
            payload = [{**payload[0], "free_qty": 0.0}]
        if payload is None:
            return httpx.Response(404, json={"diagnostic": _SENTINEL}, request=request)
        return httpx.Response(200, json=payload, request=request)


async def _new_test_state() -> tuple[object, async_sessionmaker[AsyncSession], object]:
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
                po_number="PO-001",
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


async def _assert_receipt_persists_before_crm_step() -> None:
    engine, base_sessions, order_id = await _new_test_state()
    tracking = _TrackingSessionMaker(base_sessions)
    fake = _OdooFake(
        tracking,
        checkpoint_sessionmaker=base_sessions,
        checkpoint_order_id=order_id,
    )
    fake.assert_no_transaction_on_request = True
    adapter = OdooERPAdapter(
        _runtime_settings(Settings().database_url),
        transport=fake,
        sessionmaker=tracking,
        policy=_runtime_policy(),
    )
    coordinator_session = base_sessions()
    tracking.sessions.append(coordinator_session)
    try:
        from opsflow.application.orders import get_order

        async with base_sessions() as verification_session:
            seeded = await get_order(verification_session, order_id)
        assert seeded.order.customer_reference == "CUST-001"
        assert seeded.order.po_number == "PO-001"
        result = await execute_next_order_sync(coordinator_session, adapter)
        assert result.kind is ExecuteNextKind.NEEDS_REVIEW
        assert result.order_id == order_id
        assert result.state is OrderState.FAILED_RETRYABLE
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
        assert len(fake.bridge_calls) == 1, (
            f"failure={None if sync is None else sync.last_failure_code}, "
            f"provider_paths={[path for path, _ in fake.calls]}"
        )
        assert sync is not None
        assert sync.odoo_sale_order_id == 9001
        assert sync.odoo_sale_order_name == "S009001"
        assert sync.last_failure_code == OrderSyncFailureCode.INTEGRATION_CONFIG.value
        assert order is not None
        assert order.state == OrderState.FAILED_RETRYABLE.value
        assert order.customer_reference == "CUST-001"
        assert order.po_number == "PO-001"
        assert order.currency == "USD"
        assert fake.calls[-1][0] == "/json/2/sale.order/opsflow_create_or_get_sale_order"
        assert not any("hubspot" in path for path, _ in fake.calls)
    finally:
        await coordinator_session.close()
        await adapter.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_lost_response_replays_same_identity() -> None:
    engine, base_sessions, order_id = await _new_test_state()
    tracking = _TrackingSessionMaker(base_sessions)
    fake = _OdooFake(
        tracking,
        checkpoint_sessionmaker=base_sessions,
        checkpoint_order_id=order_id,
    )
    fake.lose_first_bridge_response = True
    adapter = OdooERPAdapter(
        _runtime_settings(Settings().database_url),
        transport=fake,
        sessionmaker=tracking,
        policy=_runtime_policy(),
    )
    first_session = base_sessions()
    tracking.sessions.append(first_session)
    try:
        first = await execute_next_order_sync(first_session, adapter)
        assert first.kind is ExecuteNextKind.RETRY_WAIT
        assert first.state is OrderState.SYNCING
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.attempt_count == 1
        assert sync.last_failure_code == OrderSyncFailureCode.PROVIDER_UNAVAILABLE.value
        assert sync.in_flight_step == OrderSyncStep.ODOO_BRIDGE.value
        assert sync.odoo_sale_order_id is None
        assert len(fake.receipts) == 1
        fake.remove_stock_after_request_count = fake.requests_started

        async with base_sessions() as session, session.begin():
            await session.execute(
                update(OrderSyncModel)
                .where(OrderSyncModel.order_id == order_id)
                .values(next_attempt_at=func.now() - timedelta(seconds=1))
            )

        second_session = base_sessions()
        tracking.sessions.append(second_session)
        second = await execute_next_order_sync(second_session, adapter)
        assert second.kind is ExecuteNextKind.NEEDS_REVIEW
        assert second.state is OrderState.FAILED_RETRYABLE
        assert len(fake.bridge_calls) == 2
        first_payload, replay_payload = fake.bridge_calls
        assert first_payload == replay_payload
        assert first_payload["opsflow_order_id"] == str(order_id)
        assert len(fake.receipts) == 1

        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            audit = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
        assert sync is not None
        assert sync.odoo_sale_order_id == 9001
        assert sync.odoo_sale_order_name == "S009001"
        assert sync.attempt_count == 1
        assert any(event.event_type == "ORDER_SYNC_FAILED" for event in audit)
        assert all(_SENTINEL not in event.description for event in audit)
    finally:
        await first_session.close()
        await adapter.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_bridge_preflights_current_price_for_new_order() -> None:
    engine, base_sessions, order_id = await _new_test_state()
    tracking = _TrackingSessionMaker(base_sessions)
    fake = _OdooFake(
        tracking,
        checkpoint_sessionmaker=base_sessions,
        checkpoint_order_id=order_id,
    )
    # The first seven JSON-2 requests complete ODOO_LOOKUP. The bridge-step
    # product read then observes a price outside the approved tolerance.
    fake.change_product_price_after_request_count = 7
    adapter = OdooERPAdapter(
        _runtime_settings(Settings().database_url),
        transport=fake,
        sessionmaker=tracking,
        policy=_runtime_policy(),
    )
    coordinator_session = base_sessions()
    tracking.sessions.append(coordinator_session)
    try:
        result = await execute_next_order_sync(coordinator_session, adapter)
        assert result.kind is ExecuteNextKind.NEEDS_REVIEW
        assert result.state is OrderState.FAILED_RETRYABLE
        assert fake.bridge_calls == []
        assert fake.receipts == {}
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
        assert sync is not None
        assert sync.last_failure_code == OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED.value
        assert sync.in_flight_step == OrderSyncStep.ODOO_BRIDGE.value
    finally:
        await coordinator_session.close()
        await adapter.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_executor_runs_without_open_transactions() -> None:
    engine, base_sessions, order_id = await _new_test_state()
    tracking = _TrackingSessionMaker(base_sessions)
    fake = _OdooFake(
        tracking,
        checkpoint_sessionmaker=base_sessions,
        checkpoint_order_id=order_id,
    )
    fake.assert_no_transaction_on_request = True
    adapter = OdooERPAdapter(
        _runtime_settings(Settings().database_url),
        transport=fake,
        sessionmaker=tracking,
        policy=_runtime_policy(),
    )
    coordinator_session = base_sessions()
    tracking.sessions.append(coordinator_session)
    try:
        await execute_next_order_sync(coordinator_session, adapter)
        assert len(fake.calls) == 16
        assert sum(path == "/json/2/sale.order/search_read" for path, _ in fake.calls) == 1
        assert all(not session.in_transaction() for session in tracking.sessions)
    finally:
        await coordinator_session.close()
        await adapter.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_multi_call_executor_obeys_m9b_allowance() -> None:
    engine, base_sessions, order_id = await _new_test_state()
    tracking = _TrackingSessionMaker(base_sessions)
    fake = _OdooFake(
        tracking,
        checkpoint_sessionmaker=base_sessions,
        checkpoint_order_id=order_id,
    )
    fake.delay_seconds = 0.08
    fake.assert_no_transaction_on_request = True
    adapter = OdooERPAdapter(
        _runtime_settings(Settings().database_url),
        transport=fake,
        sessionmaker=tracking,
        policy=_runtime_policy(),
    )
    coordinator_session = base_sessions()
    tracking.sessions.append(coordinator_session)
    import opsflow.application.order_sync as order_sync_application

    original_timeouts = order_sync_application._STEP_TIMEOUTS
    assert timedelta(seconds=210) == order_sync_application._EXECUTION_BUDGET
    assert original_timeouts[OrderSyncStep.ODOO_LOOKUP] == timedelta(seconds=20)
    assert timedelta(seconds=5) == order_sync_application._RECEIPT_TRANSACTION_ALLOWANCE
    order_sync_application._STEP_TIMEOUTS = {
        **original_timeouts,
        OrderSyncStep.ODOO_LOOKUP: timedelta(milliseconds=120),
    }
    try:
        started = time.monotonic()
        result = await execute_next_order_sync(coordinator_session, adapter)
        elapsed = time.monotonic() - started
        assert result.kind is ExecuteNextKind.RETRY_WAIT
        assert result.state is OrderState.SYNCING
        assert elapsed < 0.7
        assert fake.requests_started >= 2
        assert fake.cancelled
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            order = await session.get(OrderModel, order_id)
        assert sync is not None
        assert sync.attempt_count == 1
        assert sync.claim_token is None and sync.claim_expires_at is None
        assert sync.in_flight_step == OrderSyncStep.ODOO_LOOKUP.value
        assert order is not None and order.state == OrderState.SYNCING.value
        assert await adapter._json2_call("res.company", "read", ids=[1], fields=["id"]) == [
            {"id": 1, "currency_id": [10, "USD"], "active": True}
        ]
    finally:
        order_sync_application._STEP_TIMEOUTS = original_timeouts
        await coordinator_session.close()
        await adapter.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_provider_details_are_not_persisted() -> None:
    engine, base_sessions, order_id = await _new_test_state()
    tracking = _TrackingSessionMaker(base_sessions)
    fake = _OdooFake(
        tracking,
        checkpoint_sessionmaker=base_sessions,
        checkpoint_order_id=order_id,
    )
    fake.lose_first_bridge_response = True
    adapter = OdooERPAdapter(
        _runtime_settings(Settings().database_url),
        transport=fake,
        sessionmaker=tracking,
        policy=_runtime_policy(),
    )
    coordinator_session = base_sessions()
    tracking.sessions.append(coordinator_session)
    try:
        result = await execute_next_order_sync(coordinator_session, adapter)
        assert result.kind is ExecuteNextKind.RETRY_WAIT
        assert all(sentinel not in repr(result) for sentinel in _ALL_SENTINELS)
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            audit = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
        assert sync is not None
        assert sync.last_failure_code == OrderSyncFailureCode.PROVIDER_UNAVAILABLE.value
        assert all(sentinel not in sync.last_failure_code for sentinel in _ALL_SENTINELS)
        assert all(
            sentinel not in event.description for event in audit for sentinel in _ALL_SENTINELS
        )
    finally:
        await coordinator_session.close()
        await adapter.aclose()
        await _dispose(engine, base_sessions, order_id)


async def _assert_provider_details_are_not_exposed(caplog) -> None:
    engine, base_sessions, order_id = await _new_test_state()
    tracking = _TrackingSessionMaker(base_sessions)
    fake = _OdooFake(
        tracking,
        checkpoint_sessionmaker=base_sessions,
        checkpoint_order_id=order_id,
    )
    fake.lose_first_bridge_response = True
    adapter = OdooERPAdapter(
        _runtime_settings(Settings().database_url),
        transport=fake,
        sessionmaker=tracking,
        policy=_runtime_policy(),
    )
    app_settings = Settings(
        _env_file=None,
        database_url=Settings().database_url,
        orchestration_token=_SERVICE_TOKEN,
    )
    app = create_app(app_settings)
    app.state.order_sync_step_executor = adapter
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(_EXECUTE_PATH, headers=_AUTH)
        assert response.status_code == 200
        assert response.json() == {
            "result": "retry_wait",
            "order_id": str(order_id),
            "state": "SYNCING",
        }
        assert all(sentinel not in response.text for sentinel in _ALL_SENTINELS)
        async with base_sessions() as session:
            sync = await session.get(OrderSyncModel, order_id)
            audits = tuple(
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            )
        assert sync is not None
        assert sync.last_failure_code == OrderSyncFailureCode.PROVIDER_UNAVAILABLE.value
        assert all(sentinel not in sync.last_failure_code for sentinel in _ALL_SENTINELS)
        assert all(
            sentinel not in event.description for event in audits for sentinel in _ALL_SENTINELS
        )
        assert all(sentinel not in caplog.text for sentinel in _ALL_SENTINELS)
    finally:
        await adapter.aclose()
        await _dispose(engine, base_sessions, order_id)


def _run_alembic(*arguments: str) -> None:
    subprocess.run(
        ["uv", "run", "alembic", *arguments],
        cwd=_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _dispose(engine, sessions, order_id) -> None:
    async with sessions() as session, session.begin():
        await session.execute(delete(OrderModel).where(OrderModel.id == order_id))
    await engine.dispose()


_ALL_SENTINELS = (_RESPONSE_SENTINEL, _TRACEBACK_SENTINEL, _API_KEY_SENTINEL)
