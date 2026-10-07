"""M10D diagnostics endpoint and public probe contracts."""

import asyncio

import httpx

from opsflow.main import create_app
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

VIEW_TOKEN = "m10d-view-token"
ORCHESTRATION_TOKEN = "m10d-orchestration-token"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        orchestration_token=ORCHESTRATION_TOKEN,
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=VIEW_TOKEN,
                actor="m10d-viewer",
                role=OperatorRole.REVIEWER,
            ),
        ),
    )


def test_diagnostics_are_human_view_only_and_probes_remain_public() -> None:
    asyncio.run(_assert_diagnostics_authentication())


async def _assert_diagnostics_authentication() -> None:
    async def available(engine: object) -> bool:
        del engine
        return True

    import opsflow.main as main_module

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
            metrics_missing = await client.get("/v1/operations/metrics")
            metrics_service = await client.get(
                "/v1/operations/metrics",
                headers={"Authorization": f"Bearer {ORCHESTRATION_TOKEN}"},
            )
            metrics_view = await client.get(
                "/v1/operations/metrics",
                headers={"Authorization": f"Bearer {VIEW_TOKEN}"},
            )
            integrations_view = await client.get(
                "/v1/operations/integrations",
                headers={"Authorization": f"Bearer {VIEW_TOKEN}"},
            )
            health = await client.get("/health")
            ready = await client.get("/ready")
    finally:
        main_module.database_is_available = original

    assert metrics_missing.status_code == 401
    assert metrics_service.status_code == 401
    assert metrics_view.status_code == 200
    assert set(metrics_view.json()) == {"counters", "histograms"}
    assert integrations_view.status_code == 200
    assert set(integrations_view.json()) == {"integrations"}
    assert health.status_code == 200
    assert ready.status_code == 200


def test_body_limit_rejection_is_streaming_and_receives_correlation_id() -> None:
    asyncio.run(_assert_body_limit_correlation())


async def _assert_body_limit_correlation() -> None:
    app = create_app(_settings())
    body = b"{" + b'"oversized":"' + (b"x" * (512 * 1024)) + b'"}'
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(
                "/v1/orders",
                content=body,
                headers={"X-Request-ID": "m10d-body-limit"},
            )
    finally:
        await app.state.database_engine.dispose()

    assert response.status_code == 413
    assert response.headers["X-Request-ID"] == "m10d-body-limit"
    assert response.json() == {
        "detail": {
            "code": "REQUEST_TOO_LARGE",
            "message": "The request body exceeds the allowed size.",
        }
    }
    assert "oversized" not in response.text
