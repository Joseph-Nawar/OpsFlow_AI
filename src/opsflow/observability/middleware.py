"""Pure-ASGI request correlation and HTTP completion instrumentation."""

from __future__ import annotations

import time
from typing import Any

from opsflow.observability.context import (
    CorrelationContext,
    correlation_context,
    generate_request_id,
    normalize_request_id,
    normalize_workflow_execution_id,
)
from opsflow.observability.runtime import (
    Observability,
    duration_ms,
    reset_observability,
    set_observability,
)

_N8N_WORKFLOW_ROUTES = {
    "/v1/orchestration/intakes",
    "/v1/orchestration/order-sync/execute-next",
    "/v1/integrations/notifications/claim",
    "/v1/integrations/notifications/{notification_id}/outcome",
}


class RequestCorrelationMiddleware:
    """Set bounded request context without reading or buffering request bodies."""

    def __init__(self, app: Any, *, observability: Observability | None = None) -> None:
        self.app = app
        self.observability = observability or Observability({})

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        request_id = normalize_request_id(headers.get(b"x-request-id", b"").decode("latin-1"))
        if request_id is None:
            request_id = generate_request_id()
        workflow_id = normalize_workflow_execution_id(
            headers.get(b"x-workflow-execution-id", b"").decode("latin-1")
        )
        context_token = correlation_context.set(CorrelationContext(request_id, workflow_id))
        observer_token = set_observability(self.observability)
        start_ns = time.perf_counter_ns()
        response_status: int | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal response_status
            if message.get("type") == "http.response.start":
                response_status = message.get("status")
                response_headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self._emit_http(scope, response_status, start_ns)
            raise
        else:
            self._emit_http(scope, response_status, start_ns)
        finally:
            reset_observability(observer_token)
            correlation_context.reset(context_token)

    def _emit_http(self, scope: dict[str, Any], status: int | None, start_ns: int) -> None:
        if status is None or scope.get("method") == "OPTIONS":
            return
        route = _route_template(scope)
        status_class = f"{status // 100}xx" if isinstance(status, int) else "unknown"
        elapsed = duration_ms(start_ns)
        labels = {"route": route, "status_class": status_class, "status_code": status}
        self.observability.metrics.increment("http_requests_total", labels=labels)
        self.observability.metrics.observe("http_request_duration_ms", elapsed, labels=labels)
        context = correlation_context.get()
        if (
            context is not None
            and context.workflow_execution_id is not None
            and route in _N8N_WORKFLOW_ROUTES
        ):
            if 200 <= status < 400:
                self.observability.integrations.observe_success("n8n")
            else:
                self.observability.integrations.observe_failure("n8n", "PROVIDER_UNAVAILABLE")
        self.observability.emit(
            event="http_request_completed",
            http_method=scope.get("method"),
            route=route,
            status_code=status,
            state="SUCCESS" if status < 400 else "FAILURE",
            duration_ms=elapsed,
        )


def _route_template(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    path = scope.get("path")
    if not isinstance(path, str):
        return "unmatched"
    if path in {
        "/health",
        "/ready",
        "/v1/orders",
        "/v1/orchestration/intakes",
        "/v1/orchestration/order-sync/execute-next",
        "/v1/integrations/notifications/claim",
        "/v1/operations/metrics",
        "/v1/operations/integrations",
    }:
        return path
    parts = path.strip("/").split("/")
    if len(parts) == 3 and parts[:2] == ["v1", "orders"]:
        return "/v1/orders/{order_id}"
    if len(parts) == 4 and parts[:2] == ["v1", "orders"] and parts[3] == "audit":
        return "/v1/orders/{order_id}/audit"
    if len(parts) == 5 and parts[:3] == ["v1", "integrations", "notifications"]:
        return "/v1/integrations/notifications/{notification_id}/outcome"
    return "unmatched"


__all__ = ["RequestCorrelationMiddleware"]
