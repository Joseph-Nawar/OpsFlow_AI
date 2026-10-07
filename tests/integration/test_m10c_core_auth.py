"""M10C credential separation for core order routes and probes."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx

import opsflow.api.orders as orders_api
import opsflow.main as main_module
from opsflow.application.errors import OrderNotFoundError
from opsflow.domain import Order
from opsflow.main import create_app
from opsflow.persistence.repositories import PersistedOrder
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

ORCHESTRATION_TOKEN = "m10c-core-orchestration-token"
REVIEWER_TOKEN = "m10c-core-reviewer-token"
APPROVER_TOKEN = "m10c-core-approver-token"
ELEVATED_TOKEN = "m10c-core-elevated-token"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        orchestration_token=ORCHESTRATION_TOKEN,
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=REVIEWER_TOKEN, actor="m10c-reviewer", role=OperatorRole.REVIEWER
            ),
            DevelopmentOperatorConfig(
                token=APPROVER_TOKEN, actor="m10c-approver", role=OperatorRole.APPROVER
            ),
            DevelopmentOperatorConfig(
                token=ELEVATED_TOKEN,
                actor="m10c-elevated",
                role=OperatorRole.ELEVATED_APPROVER,
            ),
        ),
    )


def test_core_reads_require_server_resolved_human_view_access() -> None:
    asyncio.run(_assert_core_read_authentication())


async def _assert_core_read_authentication() -> None:
    original_list = orders_api.application_list_orders
    original_get = orders_api.application_get_order
    original_audit = orders_api.application_get_order_audit

    async def empty_list(session, limit, offset):
        del session, limit, offset
        return (), 0

    async def missing_order(session, order_id):
        del session
        raise OrderNotFoundError(order_id)

    async def missing_audit(session, order_id):
        del session
        raise OrderNotFoundError(order_id)

    orders_api.application_list_orders = empty_list
    orders_api.application_get_order = missing_order
    orders_api.application_get_order_audit = missing_audit
    app = create_app(_settings())
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            routes = (
                "/v1/orders",
                f"/v1/orders/{uuid4()}",
                f"/v1/orders/{uuid4()}/audit",
            )
            for path in routes:
                unauthenticated = await client.get(path)
                invalid = await client.get(
                    path, headers={"Authorization": "Bearer invalid-core-token"}
                )
                orchestration = await client.get(
                    path, headers={"Authorization": f"Bearer {ORCHESTRATION_TOKEN}"}
                )
                assert unauthenticated.status_code == 401
                assert invalid.status_code == 401
                assert orchestration.status_code == 401
                for token in (REVIEWER_TOKEN, APPROVER_TOKEN, ELEVATED_TOKEN):
                    response = await client.get(
                        path,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "X-Operator-Actor": "forged-actor",
                            "X-Operator-Role": "ELEVATED_APPROVER",
                        },
                    )
                    assert response.status_code in {200, 404}
                    assert "forged-actor" not in response.text
                    assert "ELEVATED_APPROVER" not in response.text
    finally:
        orders_api.application_list_orders = original_list
        orders_api.application_get_order = original_get
        orders_api.application_get_order_audit = original_audit


def test_structured_core_create_requires_only_orchestration_bearer() -> None:
    asyncio.run(_assert_core_create_authentication())


async def _assert_core_create_authentication() -> None:
    persisted = PersistedOrder(
        Order.received(id=uuid4()),
        datetime.now(UTC),
        (),
    )

    async def fake_create(session, request, idempotency_key):
        del session, request, idempotency_key
        return persisted

    original = orders_api.application_create_order
    orders_api.application_create_order = fake_create
    app = create_app(_settings())
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            body = {"customer_reference": "CUST-M10C"}
            no_token = await client.post(
                "/v1/orders", json=body, headers={"Idempotency-Key": "m10c-create-1"}
            )
            human = await client.post(
                "/v1/orders",
                json=body,
                headers={
                    "Idempotency-Key": "m10c-create-2",
                    "Authorization": f"Bearer {REVIEWER_TOKEN}",
                },
            )
            orchestration = await client.post(
                "/v1/orders",
                json=body,
                headers={
                    "Idempotency-Key": "m10c-create-3",
                    "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                },
            )
            assert no_token.status_code == 401
            assert human.status_code == 401
            assert orchestration.status_code == 201
    finally:
        orders_api.application_create_order = original


def test_health_and_ready_remain_public() -> None:
    asyncio.run(_assert_public_probes())


async def _assert_public_probes() -> None:
    async def available(engine):
        del engine
        return True

    original = main_module.database_is_available
    main_module.database_is_available = available
    app = create_app(_settings())
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            health = await client.get("/health")
            ready = await client.get("/ready")
        assert health.status_code == 200
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready", "checks": {"database": "ok"}}
    finally:
        main_module.database_is_available = original
