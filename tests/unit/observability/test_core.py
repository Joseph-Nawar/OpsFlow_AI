"""Deterministic M10D correlation, events, metrics, and passive-health tests."""

import asyncio
import json
import logging
from typing import Any

import pytest

from opsflow.observability.context import (
    CorrelationContext,
    correlation_context,
    normalize_request_id,
    normalize_workflow_execution_id,
)
from opsflow.observability.events import StructuredEventLogger
from opsflow.observability.integrations import IntegrationHealthRegistry
from opsflow.observability.metrics import MetricsRegistry
from opsflow.observability.middleware import RequestCorrelationMiddleware
from opsflow.observability.runtime import Observability


async def _run_asgi(
    application: Any,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    method: str = "POST",
    path: str = "/v1/orders",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": headers or [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 1),
        "http_version": "1.1",
    }
    messages = iter(
        [
            {"type": "http.request", "body": body, "more_body": False},
        ]
    )
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        try:
            return next(messages)
        except StopIteration:
            return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await application(scope, receive, send)
    response_start = next(message for message in sent if message["type"] == "http.response.start")
    return response_start, sent


def test_correlation_values_are_bounded_and_safe() -> None:
    assert normalize_request_id("req-123.A:_ok") == "req-123.A:_ok"
    assert normalize_workflow_execution_id("exec-123") == "exec-123"
    assert normalize_request_id("") is None
    assert normalize_request_id("x" * 129) is None
    assert normalize_request_id("contains space") is None
    assert normalize_request_id("ümlaut") is None
    assert normalize_workflow_execution_id("bad/value") is None


def test_request_correlation_is_generated_echoed_and_context_is_cleared() -> None:
    observed: list[CorrelationContext | None] = []

    async def downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del receive
        observed.append(correlation_context.get())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def exercise() -> None:
        wrapped = RequestCorrelationMiddleware(downstream)
        start, _ = await _run_asgi(wrapped)
        headers = dict(start["headers"])
        assert b"x-request-id" in headers
        assert len(headers[b"x-request-id"]) == 36
        assert correlation_context.get() is None

    asyncio.run(exercise())
    assert len(observed) == 1
    assert observed[0] is not None
    assert observed[0].workflow_execution_id is None


def test_concurrent_requests_keep_correlation_contexts_isolated() -> None:
    observed: dict[str, str] = {}

    async def downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del receive
        context = correlation_context.get()
        assert context is not None
        await asyncio.sleep(0)
        observed[scope["path"]] = context.request_id
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def exercise() -> None:
        wrapped = RequestCorrelationMiddleware(downstream)
        await asyncio.gather(
            _run_asgi(wrapped, headers=[(b"x-request-id", b"request-one")], path="/one"),
            _run_asgi(wrapped, headers=[(b"x-request-id", b"request-two")], path="/two"),
        )

    asyncio.run(exercise())
    assert observed == {"/one": "request-one", "/two": "request-two"}


def test_valid_request_and_workflow_ids_are_retained_but_invalid_workflow_is_omitted() -> None:
    observed: list[CorrelationContext] = []

    async def downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del receive
        context = correlation_context.get()
        assert context is not None
        observed.append(context)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def exercise() -> None:
        wrapped = RequestCorrelationMiddleware(downstream)
        await _run_asgi(
            wrapped,
            headers=[
                (b"x-request-id", b"request-from-caller"),
                (b"x-workflow-execution-id", b"workflow/invalid"),
            ],
        )

    asyncio.run(exercise())
    assert observed == [CorrelationContext("request-from-caller", None)]


def test_context_does_not_change_business_result_for_same_request() -> None:
    results: list[tuple[str, str]] = []

    async def downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope, receive
        context = correlation_context.get()
        assert context is not None
        results.append(("same-idempotent-result", context.request_id))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"same"})

    async def exercise() -> None:
        wrapped = RequestCorrelationMiddleware(downstream)
        await _run_asgi(wrapped, headers=[(b"x-request-id", b"first")])
        await _run_asgi(wrapped, headers=[(b"x-request-id", b"second")])

    asyncio.run(exercise())
    assert results == [("same-idempotent-result", "first"), ("same-idempotent-result", "second")]


def test_structured_events_are_allowlisted_and_never_include_payload_or_exception(
    caplog: Any,
) -> None:
    logger = StructuredEventLogger(logging.getLogger("test.opsflow.observability"))
    with caplog.at_level(logging.INFO, logger="test.opsflow.observability"):
        logger.emit(
            event="provider_call_completed",
            provider="gemini",
            operation="structured_generation",
            state="FAILURE",
            failure_code="PROVIDER_TIMEOUT",
            duration_ms=12,
            request_id="request-safe",
            workflow_execution_id="workflow-safe",
            order_id="00000000-0000-0000-0000-000000000001",
        )

    line = caplog.records[-1].message
    parsed = json.loads(line)
    assert parsed["event"] == "provider_call_completed"
    assert parsed["provider"] == "gemini"
    assert "forbidden_values" not in parsed
    assert "raw exception text" not in line


def test_metrics_are_bounded_and_exclude_high_cardinality_labels() -> None:
    metrics = MetricsRegistry()
    metrics.increment(
        "http_requests_total",
        labels={
            "route": "/v1/orders/{order_id}",
            "status_class": "2xx",
            "request_id": "request-high-cardinality",
            "order_id": "order-high-cardinality",
        },
    )
    metrics.increment(
        "http_requests_total",
        labels={"route": "/v1/orders/00000000-0000-0000-0000-000000000001"},
    )
    metrics.observe(
        "http_request_duration_ms",
        12.4,
        labels={"route": "/v1/orders/{order_id}", "status_class": "2xx"},
    )
    snapshot = metrics.snapshot()
    serialized = json.dumps(snapshot, sort_keys=True)
    assert "request-high-cardinality" not in serialized
    assert "order-high-cardinality" not in serialized
    assert "00000000-0000-0000-0000-000000000001" not in serialized
    assert (
        snapshot["counters"]["http_requests_total"]["route=/v1/orders/{order_id},status_class=2xx"]
        == 1
    )
    assert (
        snapshot["histograms"]["http_request_duration_ms"][
            "route=/v1/orders/{order_id},status_class=2xx"
        ]["count"]
        == 1
    )


def test_passive_integration_health_observes_only_explicit_real_operations() -> None:
    health = IntegrationHealthRegistry(
        {
            "gemini": "CONFIGURED",
            "gmail": "EXTERNALLY_MANAGED",
        }
    )
    before = health.snapshot()
    assert before["gemini"]["observation"] == "NOT_OBSERVED"
    assert before["gmail"]["configuration"] == "EXTERNALLY_MANAGED"
    health.observe_success("gemini")
    health.observe_failure("gmail", "PROVIDER_UNAVAILABLE")
    after = health.snapshot()
    assert after["gemini"]["observation"] == "HEALTHY"
    assert after["gmail"]["observation"] == "UNAVAILABLE"
    assert after["gmail"]["failure_code"] == "PROVIDER_UNAVAILABLE"


def test_public_probe_with_workflow_header_does_not_claim_n8n_health() -> None:
    observed = IntegrationHealthRegistry({"n8n": "EXTERNALLY_MANAGED"})

    async def downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope, receive
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def exercise() -> None:
        wrapped = RequestCorrelationMiddleware(downstream, observability=_observer(observed))
        await _run_asgi(
            wrapped,
            method="GET",
            path="/health",
            headers=[(b"x-workflow-execution-id", b"execution-123")],
        )

    asyncio.run(exercise())
    assert observed.snapshot()["n8n"]["observation"] == "NOT_OBSERVED"


def _observer(health: IntegrationHealthRegistry) -> Any:
    observer = Observability({"n8n": "EXTERNALLY_MANAGED"})
    observer.integrations = health
    return observer


@pytest.mark.parametrize("bad", ["x" * 129, "bad/value", "bad value"])
def test_invalid_correlation_values_are_not_retained(bad: str) -> None:
    assert normalize_request_id(bad) is None
    assert normalize_workflow_execution_id(bad) is None
