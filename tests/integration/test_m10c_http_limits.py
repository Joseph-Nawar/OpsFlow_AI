"""M10C ASGI receive-boundary and route-budget regression tests."""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from uuid import UUID

import httpx
import pytest

from opsflow.domain import OrderState
from opsflow.main import create_app
from opsflow.orchestration.contracts import (
    IntakeExecution,
    OrchestrationIntakeCommand,
    OrchestrationIntakeResult,
)
from opsflow.settings import Settings

ORCHESTRATION_TOKEN = "m10c-http-limit-orchestration-token"


async def _fake_downstream(
    scope: dict[str, Any],
    receive: Callable[[], Awaitable[dict[str, Any]]],
    send: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    del scope
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        if message["type"] == "http.request" and not message.get("more_body", False):
            break
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def _scope(
    path: str, *, content_length: int | None = None, content_type: str = "application/json"
) -> dict[str, Any]:
    headers: list[tuple[bytes, bytes]] = [(b"content-type", content_type.encode())]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 1234),
        "server": ("testserver", 80),
    }


async def _invoke(
    app: Any,
    path: str,
    chunks: Iterable[bytes],
    *,
    content_length: int | None = None,
    content_type: str = "application/json",
) -> list[dict[str, Any]]:
    messages = iter(
        [
            *({"type": "http.request", "body": chunk, "more_body": True} for chunk in chunks),
            {"type": "http.request", "body": b"", "more_body": False},
        ]
    )

    async def receive() -> dict[str, Any]:
        return next(messages)

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(
        _scope(path, content_length=content_length, content_type=content_type),
        receive,
        send,
    )
    return sent


def _status_and_body(messages: list[dict[str, Any]]) -> tuple[int, bytes]:
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return int(start["status"]), body


def test_exact_route_budgets_reach_the_downstream_asgi_app() -> None:
    from opsflow.http_limits import (
        JSON_REQUEST_LIMIT,
        NOTIFICATION_OUTCOME_LIMIT,
        ORCHESTRATION_MULTIPART_LIMIT,
        RequestBodyLimitMiddleware,
    )

    async def run() -> None:
        for path, limit, content_type in (
            ("/v1/orders", JSON_REQUEST_LIMIT, "application/json"),
            (
                "/v1/orchestration/intakes",
                ORCHESTRATION_MULTIPART_LIMIT,
                "multipart/form-data; boundary=test",
            ),
            (
                "/v1/integrations/notifications/00000000-0000-0000-0000-000000000001/outcome",
                NOTIFICATION_OUTCOME_LIMIT,
                "application/json",
            ),
        ):
            messages = await _invoke(
                RequestBodyLimitMiddleware(_fake_downstream),
                path,
                [b"x" * limit],
                content_length=limit,
                content_type=content_type,
            )
            assert _status_and_body(messages)[0] == 204

    import asyncio

    asyncio.run(run())


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/v1/orders", "application/json"),
        ("/v1/orchestration/intakes", "multipart/form-data; boundary=test"),
        (
            "/v1/integrations/notifications/00000000-0000-0000-0000-000000000001/outcome",
            "application/json",
        ),
    ],
)
def test_route_budget_plus_one_returns_safe_413(path: str, content_type: str) -> None:
    from opsflow.http_limits import (
        JSON_REQUEST_LIMIT,
        NOTIFICATION_OUTCOME_LIMIT,
        ORCHESTRATION_MULTIPART_LIMIT,
        RequestBodyLimitMiddleware,
    )

    limit = {
        "/v1/orders": JSON_REQUEST_LIMIT,
        "/v1/orchestration/intakes": ORCHESTRATION_MULTIPART_LIMIT,
    }.get(path, NOTIFICATION_OUTCOME_LIMIT)

    import asyncio

    messages = asyncio.run(
        _invoke(
            RequestBodyLimitMiddleware(_fake_downstream),
            path,
            [b"x" * (limit + 1)],
            content_length=limit + 1,
            content_type=content_type,
        )
    )
    status, body = _status_and_body(messages)
    assert status == 413
    expected = (
        b'{"detail":{"code":"REQUEST_TOO_LARGE","message":"The request body '
        b'exceeds the allowed size."}}'
    )
    assert body == expected


def test_actual_bytes_are_limited_without_content_length_or_with_misleading_length() -> None:
    import asyncio

    from opsflow.http_limits import JSON_REQUEST_LIMIT, RequestBodyLimitMiddleware

    for content_length in (None, 1):
        messages = asyncio.run(
            _invoke(
                RequestBodyLimitMiddleware(_fake_downstream),
                "/v1/orders",
                [b"x" * (JSON_REQUEST_LIMIT // 2), b"y" * (JSON_REQUEST_LIMIT // 2 + 1)],
                content_length=content_length,
            )
        )
        assert _status_and_body(messages)[0] == 413


def test_absolute_content_length_limit_rejects_before_downstream_consumption() -> None:
    import asyncio

    from opsflow.http_limits import ABSOLUTE_REQUEST_LIMIT, RequestBodyLimitMiddleware

    consumed = False

    async def receive() -> dict[str, Any]:
        nonlocal consumed
        consumed = True
        return {"type": "http.request", "body": b"x" * (ABSOLUTE_REQUEST_LIMIT + 1)}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def run() -> None:
        await RequestBodyLimitMiddleware(_fake_downstream)(
            _scope("/unmapped", content_length=ABSOLUTE_REQUEST_LIMIT + 1), receive, send
        )

    asyncio.run(run())
    assert _status_and_body(sent)[0] == 413
    assert consumed is False


async def _post_multipart(document: bytes) -> httpx.Response:
    app = create_app(Settings(_env_file=None, orchestration_token=ORCHESTRATION_TOKEN))

    async def handler(
        session: Any,
        command: OrchestrationIntakeCommand,
        actor: str,
        recorded_at: Any,
    ) -> OrchestrationIntakeResult:
        del session, command, actor, recorded_at
        return OrchestrationIntakeResult(
            order_id=UUID("00000000-0000-0000-0000-000000000001"),
            state=OrderState.NEEDS_REVIEW,
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
        return await client.post(
            "/v1/orchestration/intakes",
            data={"document_type": "CSV"},
            files={"document": ("boundary.csv", document, "text/csv")},
            headers={
                "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                "Idempotency-Key": "m10c-boundary-intake",
            },
        )


def test_exact_10_mib_document_remains_transportable_inside_multipart_budget() -> None:
    import asyncio

    response = asyncio.run(_post_multipart(b"x" * (10 * 1024 * 1024)))
    assert response.status_code == 201


def test_document_over_10_mib_fails_document_limit_before_pipeline() -> None:
    import asyncio

    response = asyncio.run(_post_multipart(b"x" * (10 * 1024 * 1024 + 1)))
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "INVALID_ORCHESTRATION_INTAKE",
            "message": "The orchestration intake request is invalid.",
        }
    }
