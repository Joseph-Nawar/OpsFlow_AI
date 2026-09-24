"""HTTP semantics consumed by the bounded n8n transport fallback."""

import asyncio
import importlib.util
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

import opsflow.main as main_module
from opsflow.domain import OrderState
from opsflow.orchestration.contracts import IntakeExecution, OrchestrationIntakeResult
from opsflow.settings import Settings

_PIPELINE_PATH = Path(__file__).with_name("test_phase7_pipeline.py")
_PIPELINE_SPEC = importlib.util.spec_from_file_location("phase7_pipeline", _PIPELINE_PATH)
assert _PIPELINE_SPEC is not None and _PIPELINE_SPEC.loader is not None
_PIPELINE = importlib.util.module_from_spec(_PIPELINE_SPEC)
_PIPELINE_SPEC.loader.exec_module(_PIPELINE)
ORCHESTRATION_TOKEN = _PIPELINE.ORCHESTRATION_TOKEN
_build_test_app = _PIPELINE._build_test_app
_delete_orders = _PIPELINE._delete_orders
_post_intake = _PIPELINE._post_intake
_read_order_evidence = _PIPELINE._read_order_evidence


def test_persisted_failed_retryable_is_2xx_business_state_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_persisted_failed_retryable(monkeypatch))


async def _assert_persisted_failed_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "task13-transport-processing"
    from datetime import date

    app = _build_test_app(
        monkeypatch,
        date(2025, 1, 1),
        extraction_provider_factory=_PIPELINE.UnavailableProvider,
    )
    order_id: UUID | None = None
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            first = await _post_intake(client, key)
            second = await _post_intake(client, key)

        assert first.status_code == 201
        assert first.json()["state"] == OrderState.FAILED_RETRYABLE.value
        assert first.json()["failure_origin"] == OrderState.PROCESSING.value
        assert second.status_code == 200
        assert second.json()["state"] == OrderState.FAILED_RETRYABLE.value
        assert second.json()["idempotent_replay"] is True
        order_id, _, events = await _read_order_evidence(key)
        assert events.count("ORDER_PROCESSING_FAILED") == 1
    finally:
        if order_id is not None:
            await _delete_orders((order_id,))


@pytest.mark.parametrize("state", (OrderState.PROCESSING, OrderState.EXTRACTED))
def test_current_state_stand_down_is_202_without_a_transport_retry(
    state: OrderState,
) -> None:
    asyncio.run(_assert_current_state_stand_down(state))


async def _assert_current_state_stand_down(state: OrderState) -> None:
    app = main_module.create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN))
    recorded: list[tuple[str, datetime]] = []

    async def handler(session, command, actor, recorded_at):
        del session, command
        recorded.append((actor, recorded_at))
        return OrchestrationIntakeResult(
            order_id=UUID("00000000-0000-0000-0000-000000000013"),
            state=state,
            failure_origin=None,
            idempotent_replay=True,
            execution=IntakeExecution.STANDING_DOWN,
        )

    app.state.orchestration_intake_handler = handler
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/v1/orchestration/intakes",
            data={"document_type": "EMAIL_BODY", "message_id": "task13-current"},
            files={"document": ("synthetic-order.txt", b"synthetic", "text/plain")},
            headers={
                "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                "Idempotency-Key": "task13-current-state",
            },
        )

    assert response.status_code == 202
    assert response.json()["state"] == state.value
    assert len(recorded) == 1
    assert recorded[0][0] == "orchestration:n8n"
    assert recorded[0][1].tzinfo is not None


def test_contradictory_completed_intermediate_state_is_bounded_503() -> None:
    asyncio.run(_assert_contradictory_completed_state())


async def _assert_contradictory_completed_state() -> None:
    app = main_module.create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN))

    async def handler(session, command, actor, recorded_at):
        del session, command, actor, recorded_at
        return OrchestrationIntakeResult(
            order_id=UUID("00000000-0000-0000-0000-000000000014"),
            state=OrderState.PROCESSING,
            failure_origin=None,
            idempotent_replay=False,
            execution=IntakeExecution.COMPLETED,
        )

    app.state.orchestration_intake_handler = handler
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            "/v1/orchestration/intakes",
            data={"document_type": "EMAIL_BODY"},
            files={"document": ("synthetic-order.txt", b"synthetic", "text/plain")},
            headers={
                "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                "Idempotency-Key": "task13-contradictory",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "ORCHESTRATION_UNAVAILABLE",
            "message": "Orchestration intake is currently unavailable.",
        }
    }
