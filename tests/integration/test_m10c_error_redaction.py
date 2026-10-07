"""M10C proofs that client-controlled and secret values stay out of errors."""

import asyncio

import httpx

import opsflow.api.orders as orders_api
from opsflow.domain import DomainValidationError
from opsflow.main import create_app
from opsflow.settings import Settings

ORCHESTRATION_TOKEN = "m10c-error-orchestration-token"
SECRET_SENTINEL = "SECRET_SENTINEL_DO_NOT_ECHO"


def test_core_domain_validation_returns_a_stable_non_echoing_error(monkeypatch) -> None:
    asyncio.run(_assert_core_domain_validation_is_safe(monkeypatch))


async def _assert_core_domain_validation_is_safe(monkeypatch) -> None:
    async def reject_order(session, request, idempotency_key):
        del session, request, idempotency_key
        raise DomainValidationError(
            f"{SECRET_SENTINEL} postgresql://secret@example.invalid/orders SELECT * FROM orders"
        )

    monkeypatch.setattr(orders_api, "application_create_order", reject_order)
    app = create_app(Settings(_env_file=None, orchestration_token=ORCHESTRATION_TOKEN))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/v1/orders",
            json={},
            headers={
                "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                "Idempotency-Key": "m10c-safe-error-1",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "INVALID_ORDER",
            "message": "The submitted order is invalid.",
        }
    }
    assert SECRET_SENTINEL not in response.text
    assert "postgresql://" not in response.text
    assert "SELECT *" not in response.text
    assert "Traceback" not in response.text


def test_request_validation_returns_a_stable_non_echoing_error() -> None:
    asyncio.run(_assert_request_validation_is_safe())


async def _assert_request_validation_is_safe() -> None:
    app = create_app(Settings(_env_file=None, orchestration_token=ORCHESTRATION_TOKEN))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/v1/orders",
            json={"lines": [{"quantity": SECRET_SENTINEL}]},
            headers={
                "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                "Idempotency-Key": "m10c-safe-error-2",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "INVALID_REQUEST",
            "message": "The request is invalid.",
        }
    }
    assert SECRET_SENTINEL not in response.text
    assert "Traceback" not in response.text
    assert "postgresql://" not in response.text


def test_provider_configuration_error_contract_is_bounded() -> None:
    asyncio.run(_assert_provider_configuration_error_is_safe())


async def _assert_provider_configuration_error_is_safe() -> None:
    app = create_app(Settings(_env_file=None, orchestration_token=ORCHESTRATION_TOKEN))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/v1/orchestration/order-sync/execute-next",
            headers={"Authorization": f"Bearer {ORCHESTRATION_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "ORDER_SYNC_UNAVAILABLE",
            "message": "Order synchronization is currently unavailable.",
        }
    }
    assert ORCHESTRATION_TOKEN not in response.text
    assert "postgresql://" not in response.text
    assert "Traceback" not in response.text
