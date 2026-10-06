"""Streaming ASGI request-body limits for the local HTTP boundary."""

from collections.abc import Awaitable, Callable
from typing import cast

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

ABSOLUTE_REQUEST_LIMIT = 12 * 1024 * 1024
ORCHESTRATION_MULTIPART_LIMIT = 11 * 1024 * 1024
JSON_REQUEST_LIMIT = 512 * 1024
NOTIFICATION_OUTCOME_LIMIT = 16 * 1024

_NOTIFICATION_OUTCOME_SUFFIX = "/outcome"
_JSON_CONTENT_TYPES = {"application/json", "application/merge-patch+json"}


class _RequestBodyTooLarge(Exception):
    """Internal signal raised when the receive stream exceeds its budget."""


class RequestBodyLimitMiddleware:
    """Reject oversized bodies before Starlette parses or buffers them fully."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _request_limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return

        content_length = _content_length(scope)
        if content_length is not None and content_length > limit:
            await _send_too_large(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] != "http.request":
                return message
            body = message.get("body", b"")
            received_bytes += len(body)
            if received_bytes > limit:
                raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await _send_too_large(scope, receive, send)


def _request_limit(scope: Scope) -> int | None:
    """Return the smallest applicable budget without inspecting request bytes."""

    method = str(scope.get("method", "")).upper()
    path = str(scope.get("path", ""))
    if method in {"GET", "HEAD", "OPTIONS"}:
        return None
    if method == "POST" and path == "/v1/orchestration/intakes":
        return ORCHESTRATION_MULTIPART_LIMIT
    if (
        method == "POST"
        and path.startswith("/v1/integrations/notifications/")
        and path.endswith(_NOTIFICATION_OUTCOME_SUFFIX)
    ):
        return NOTIFICATION_OUTCOME_LIMIT
    if _content_type(scope) in _JSON_CONTENT_TYPES or _content_type(scope).endswith("+json"):
        return JSON_REQUEST_LIMIT
    return ABSOLUTE_REQUEST_LIMIT


def _content_type(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-type":
            raw_value = cast(bytes, value)
            return raw_value.split(b";", 1)[0].strip().lower().decode("latin-1")
    return ""


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(cast(bytes, value).decode("ascii"), 10)
        except (UnicodeDecodeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
    return None


async def _send_too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse(
        status_code=413,
        content={
            "detail": {
                "code": "REQUEST_TOO_LARGE",
                "message": "The request body exceeds the allowed size.",
            }
        },
    )
    await response(scope, receive, send)
