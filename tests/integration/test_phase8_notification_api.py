"""Service-authenticated notification API status and safe-body matrix."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError
from test_phase8_notification_persistence import _dispose, _seed_delivery

import opsflow.api.notifications as notification_api
from opsflow.main import create_app
from opsflow.persistence.models import NotificationDeliveryModel
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

SERVICE_TOKEN = "synthetic-notification-service-token"
REVIEW_TOKEN = "synthetic-review-user-token"
_AUTH = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


def test_notification_api_routes_are_registered_with_bounded_schemas() -> None:
    openapi = create_app(_settings()).openapi()
    paths = openapi["paths"]
    assert set(path for path in paths if path.startswith("/v1/integrations/notifications")) == {
        "/v1/integrations/notifications/claim",
        "/v1/integrations/notifications/{notification_id}/outcome",
    }
    claim = paths["/v1/integrations/notifications/claim"]["post"]
    outcome = paths["/v1/integrations/notifications/{notification_id}/outcome"]["post"]
    assert {"200", "204", "401", "422", "503"} <= set(claim["responses"])
    assert {"200", "401", "404", "409", "422", "503"} <= set(outcome["responses"])


def test_notification_api_rejects_missing_wrong_and_review_bearers() -> None:
    asyncio.run(_assert_authentication_matrix())


def test_claim_and_outcome_return_only_persisted_bounded_results() -> None:
    asyncio.run(_assert_claim_and_outcome())


def test_claim_returns_bodyless_204_when_no_work_is_due() -> None:
    asyncio.run(_assert_no_work_204())


def test_outcome_maps_unknown_and_stale_claims_to_bounded_errors() -> None:
    asyncio.run(_assert_unknown_and_stale())


def test_malformed_outcome_is_non_echoing_422() -> None:
    asyncio.run(_assert_malformed_outcome())


def test_database_failure_maps_to_bounded_503_without_provider_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_claim(_session: object) -> None:
        raise SQLAlchemyError("secret provider response body")

    monkeypatch.setattr(notification_api, "claim_next_notification", fail_claim)
    asyncio.run(_assert_persistence_unavailable())


def test_outcome_database_failure_maps_to_bounded_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_outcome(_session: object, _notification_id: object, _outcome: object) -> None:
        raise SQLAlchemyError("secret provider response body")

    monkeypatch.setattr(notification_api, "record_notification_outcome", fail_outcome)
    asyncio.run(_assert_outcome_persistence_unavailable())


def _settings() -> Settings:
    return Settings(
        orchestration_token=SERVICE_TOKEN,
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=REVIEW_TOKEN,
                actor="reviewer-test",
                role=OperatorRole.REVIEWER,
            ),
        ),
    )


async def _assert_authentication_matrix() -> None:
    app = create_app(_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        missing = await client.post("/v1/integrations/notifications/claim")
        wrong = await client.post(
            "/v1/integrations/notifications/claim",
            headers={"Authorization": "Bearer wrong-service-token"},
        )
        review = await client.post(
            "/v1/integrations/notifications/claim",
            headers={"Authorization": f"Bearer {REVIEW_TOKEN}"},
        )
    for response in (missing, wrong, review):
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "ORCHESTRATION_UNAUTHENTICATED"
    assert SERVICE_TOKEN not in missing.text + wrong.text + review.text
    assert REVIEW_TOKEN not in review.text


async def _assert_claim_and_outcome() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery()
    app = create_app(_settings())
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            claim_response = await client.post(
                "/v1/integrations/notifications/claim", headers=_AUTH
            )
            assert claim_response.status_code == 200, claim_response.text
            claim = claim_response.json()
            assert claim["notification_id"] == str(notification_id)
            assert claim["attempt_number"] == 1
            assert claim["payload"] == {"text": "safe test payload"}
            assert set(claim) == {
                "notification_id",
                "channel",
                "kind",
                "payload",
                "attempt_number",
                "claim_token",
                "claim_expires_at",
            }
            outcome = await client.post(
                f"/v1/integrations/notifications/{notification_id}/outcome",
                headers=_AUTH,
                json={
                    "claim_token": claim["claim_token"],
                    "outcome": "DELIVERED",
                    "provider_reference": "provider-ref-1",
                },
            )
            assert outcome.status_code == 200, outcome.text
            assert outcome.json()["status"] == "DELIVERED"
            assert outcome.json()["provider_reference"] == "provider-ref-1"
            assert set(outcome.json()) == {
                "notification_id",
                "status",
                "attempt_count",
                "next_attempt_at",
                "provider_reference",
                "failure_code",
            }
            duplicate = await client.post(
                f"/v1/integrations/notifications/{notification_id}/outcome",
                headers=_AUTH,
                json={"claim_token": claim["claim_token"], "outcome": "DELIVERED"},
            )
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"]["code"] == "STALE_NOTIFICATION_CLAIM"
            assert claim["claim_token"] not in duplicate.text
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_no_work_204() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    engine, sessions, _notification_id, order_id = await _seed_delivery(next_attempt_at=future)
    app = create_app(_settings())
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post("/v1/integrations/notifications/claim", headers=_AUTH)
        assert response.status_code == 204
        assert response.content == b""
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_unknown_and_stale() -> None:
    engine, sessions, notification_id, order_id = await _seed_delivery()
    app = create_app(_settings())
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            unknown = await client.post(
                f"/v1/integrations/notifications/{uuid4()}/outcome",
                headers=_AUTH,
                json={"claim_token": str(uuid4()), "outcome": "DELIVERED"},
            )
            claim = await client.post("/v1/integrations/notifications/claim", headers=_AUTH)
            claim_body = claim.json()
            async with sessions() as session:
                from sqlalchemy import update

                await session.execute(
                    update(NotificationDeliveryModel)
                    .where(NotificationDeliveryModel.id == notification_id)
                    .values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
                await session.commit()
            expired = await client.post(
                f"/v1/integrations/notifications/{notification_id}/outcome",
                headers=_AUTH,
                json={"claim_token": claim_body["claim_token"], "outcome": "DELIVERED"},
            )
        assert unknown.status_code == 404
        assert unknown.json()["detail"]["code"] == "NOTIFICATION_NOT_FOUND"
        assert expired.status_code == 409
        assert expired.json()["detail"]["code"] == "STALE_NOTIFICATION_CLAIM"
    finally:
        await _dispose(engine, sessions, order_id)


async def _assert_malformed_outcome() -> None:
    app = create_app(_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            f"/v1/integrations/notifications/{uuid4()}/outcome",
            headers=_AUTH,
            json={
                "claim_token": str(uuid4()),
                "outcome": "FAILED",
                "failure_code": "raw provider diagnostic token",
                "provider_body": {"message": "sensitive provider error"},
            },
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_NOTIFICATION_REQUEST"
    assert "raw provider diagnostic token" not in response.text
    assert "sensitive provider error" not in response.text


async def _assert_persistence_unavailable() -> None:
    app = create_app(_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post("/v1/integrations/notifications/claim", headers=_AUTH)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "NOTIFICATION_UNAVAILABLE"
    assert "secret provider response body" not in response.text


async def _assert_outcome_persistence_unavailable() -> None:
    app = create_app(_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            f"/v1/integrations/notifications/{uuid4()}/outcome",
            headers=_AUTH,
            json={"claim_token": str(uuid4()), "outcome": "DELIVERED"},
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "NOTIFICATION_UNAVAILABLE"
    assert "secret provider response body" not in response.text
