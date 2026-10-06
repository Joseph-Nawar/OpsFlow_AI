"""Composed observability state and best-effort seam helpers."""

from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any

from opsflow.observability.context import correlation_context
from opsflow.observability.events import StructuredEventLogger
from opsflow.observability.integrations import IntegrationHealthRegistry
from opsflow.observability.metrics import MetricsRegistry

_active_observability: ContextVar[Observability | None] = ContextVar(
    "opsflow_active_observability", default=None
)


class Observability:
    """One process-local event, metrics, and passive-health container."""

    def __init__(self, configuration: dict[str, str]) -> None:
        self.events = StructuredEventLogger()
        self.metrics = MetricsRegistry()
        self.integrations = IntegrationHealthRegistry(configuration)

    def emit(self, **fields: Any) -> None:
        context = correlation_context.get()
        if context is not None:
            fields.setdefault("request_id", context.request_id)
            fields.setdefault("workflow_execution_id", context.workflow_execution_id)
        self.events.emit(**fields)

    def provider_completed(
        self,
        *,
        provider: str,
        operation: str,
        success: bool,
        duration_ms: float,
        failure_code: str | None = None,
        order_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        state = "SUCCESS" if success else "FAILURE"
        labels: dict[str, object] = {
            "provider": provider,
            "operation": operation,
            "state": state,
        }
        if failure_code is not None:
            labels["failure_code"] = failure_code
        self.metrics.increment("provider_calls_total", labels=labels)
        self.metrics.observe("provider_duration_ms", duration_ms, labels=labels)
        self.emit(
            event="provider_call_completed",
            provider=provider,
            operation=operation,
            state=state,
            failure_code=failure_code,
            duration_ms=duration_ms,
            order_id=order_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        if success:
            self.integrations.observe_success(provider)
        else:
            self.integrations.observe_failure(provider, failure_code or "UNKNOWN_FAILURE")

    def intake_outcome(
        self,
        *,
        state: str,
        duration_ms: float,
        order_id: str | None = None,
        failure_code: str | None = None,
        retry_outcome: str | None = None,
    ) -> None:
        labels: dict[str, object] = {"state": state}
        if retry_outcome is not None:
            labels["retry_outcome"] = retry_outcome
        if failure_code is not None:
            labels["failure_code"] = failure_code
        self.metrics.increment("intake_outcomes_total", labels=labels)
        self.metrics.observe("intake_duration_ms", duration_ms, labels=labels)
        self.emit(
            event="orchestration_intake_outcome",
            operation="intake",
            state=state,
            failure_code=failure_code,
            duration_ms=duration_ms,
            order_id=order_id,
        )

    def notification_outcome(
        self,
        *,
        channel: str,
        state: str,
        duration_ms: float,
        failure_code: str | None = None,
    ) -> None:
        labels: dict[str, object] = {"channel": channel, "state": state}
        if failure_code is not None:
            labels["failure_code"] = failure_code
        self.metrics.increment("notification_outcomes_total", labels=labels)
        self.emit(
            event="notification_outcome_recorded",
            operation="notification_outcome",
            state=state,
            failure_code=failure_code,
            duration_ms=duration_ms,
        )
        if channel.lower() in {"gmail", "slack"}:
            if state == "DELIVERED":
                self.integrations.observe_success(channel.lower())
            else:
                self.integrations.observe_failure(
                    channel.lower(), failure_code or "NOTIFICATION_FAILURE"
                )

    def order_sync_outcome(
        self,
        *,
        provider: str,
        step: str,
        success: bool,
        duration_ms: float,
        order_id: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        state = "SUCCESS" if success else "FAILURE"
        labels: dict[str, object] = {"provider": provider, "step": step, "state": state}
        if failure_code is not None:
            labels["failure_code"] = failure_code
        self.metrics.increment("order_sync_steps_total", labels=labels)
        self.emit(
            event="order_sync_step_outcome",
            provider=provider,
            operation=step,
            state=state,
            failure_code=failure_code,
            duration_ms=duration_ms,
            order_id=order_id,
        )
        if provider in {"odoo", "hubspot"}:
            if success:
                self.integrations.observe_success(provider)
            else:
                self.integrations.observe_failure(provider, failure_code or "UNKNOWN_FAILURE")


def current_observability() -> Observability | None:
    """Return the request-local observer, if the call is inside the API."""

    return _active_observability.get()


def set_observability(value: Observability | None) -> object:
    """Set the request-local observer and return its reset token."""

    return _active_observability.set(value)


def reset_observability(token: object) -> None:
    """Reset the request-local observer."""

    _active_observability.reset(token)  # type: ignore[arg-type]


def duration_ms(start_ns: int) -> float:
    """Calculate a bounded monotonic duration for diagnostics."""

    return round(max(0.0, (time.perf_counter_ns() - start_ns) / 1_000_000), 3)


__all__ = [
    "Observability",
    "current_observability",
    "duration_ms",
    "reset_observability",
    "set_observability",
]
