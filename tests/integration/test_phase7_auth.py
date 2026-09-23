"""Authentication boundary tests for the Phase 7 orchestration route."""

import asyncio
from datetime import datetime
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import OrderState
from opsflow.main import create_app
from opsflow.orchestration.contracts import (
    IntakeExecution,
    OrchestrationIntakeCommand,
    OrchestrationIntakeResult,
)
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

ORCHESTRATION_TOKEN = "synthetic-orchestration-service-credential"
REVIEWER_TOKEN = "synthetic-phase6-reviewer-credential"
INTAKE_PATH = "/v1/orchestration/intakes"


def test_orchestration_route_requires_a_service_bearer_credential() -> None:
    response = asyncio.run(_post_intake())

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": {
            "code": "ORCHESTRATION_UNAUTHENTICATED",
            "message": "Orchestration service authentication is required.",
        }
    }
    assert ORCHESTRATION_TOKEN not in response.text


def test_orchestration_route_rejects_an_unknown_service_credential() -> None:
    response = asyncio.run(_post_intake(token="wrong-orchestration-credential"))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "wrong-orchestration-credential" not in response.text


def test_correct_orchestration_credential_reaches_the_authenticated_handler() -> None:
    response, calls = asyncio.run(_post_with_recording_handler())

    assert response.status_code == 201
    assert response.json()["state"] == "NEEDS_REVIEW"
    assert response.json()["idempotent_replay"] is False
    assert len(calls) == 1
    assert calls[0][2] == "orchestration:n8n"
    assert ORCHESTRATION_TOKEN not in response.text


def test_reviewer_credential_cannot_authenticate_orchestration() -> None:
    response = asyncio.run(
        _post_intake(
            token=REVIEWER_TOKEN,
            settings=Settings(
                orchestration_token=ORCHESTRATION_TOKEN,
                review_dev_operators=(
                    DevelopmentOperatorConfig(
                        token=REVIEWER_TOKEN,
                        actor="reviewer-test",
                        role=OperatorRole.REVIEWER,
                    ),
                ),
            ),
        )
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "ORCHESTRATION_UNAUTHENTICATED"
    assert REVIEWER_TOKEN not in response.text


def test_phase6_human_review_authentication_contract_remains_unchanged() -> None:
    response = asyncio.run(_post_review_command_without_credentials())

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": {
            "code": "UNAUTHENTICATED",
            "message": "Development operator authentication is required.",
        }
    }


async def _post_intake(
    *,
    token: str | None = None,
    settings: Settings | None = None,
    handler: "RecordingHandler | None" = None,
) -> httpx.Response:
    app = create_app(settings or Settings(orchestration_token=ORCHESTRATION_TOKEN))
    if handler is not None:
        app.state.orchestration_intake_handler = handler
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"Idempotency-Key": "auth-test-key"}
            if token is not None:
                headers["Authorization"] = f"Bearer {token}"
            return await client.post(
                INTAKE_PATH,
                data={"document_type": "PDF"},
                files={"document": ("auth-test.pdf", b"document", "application/pdf")},
                headers=headers,
            )


async def _post_with_recording_handler() -> tuple[
    httpx.Response,
    list[tuple[OrchestrationIntakeCommand, datetime, str]],
]:
    handler = RecordingHandler()
    response = await _post_intake(token=ORCHESTRATION_TOKEN, handler=handler)
    return response, handler.calls


class RecordingHandler:
    def __init__(self) -> None:
        self.calls: list[tuple[OrchestrationIntakeCommand, datetime, str]] = []

    async def __call__(
        self,
        session: AsyncSession,
        command: OrchestrationIntakeCommand,
        actor: str,
        recorded_at: datetime,
    ) -> OrchestrationIntakeResult:
        del session
        self.calls.append((command, recorded_at, actor))
        return OrchestrationIntakeResult(
            order_id=UUID("00000000-0000-0000-0000-000000000001"),
            state=OrderState.NEEDS_REVIEW,
            failure_origin=None,
            idempotent_replay=False,
            execution=IntakeExecution.COMPLETED,
        )


async def _post_review_command_without_credentials() -> httpx.Response:
    app = create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/v1/review/orders/00000000-0000-0000-0000-000000000001/approve",
                headers={"If-Match": '"' + "a" * 64 + '"'},
            )
