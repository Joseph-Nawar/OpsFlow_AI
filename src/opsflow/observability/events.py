"""Allowlisted machine-readable application events."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from opsflow.observability.context import normalize_request_id, normalize_workflow_execution_id

_SAFE_VALUE = re.compile(r"[A-Za-z0-9_.:/{}-]+", re.ASCII)
_EVENTS = {
    "http_request_completed",
    "provider_call_completed",
    "orchestration_intake_outcome",
    "notification_outcome_recorded",
    "order_sync_step_outcome",
}
_PROVIDERS = {"gemini", "odoo", "hubspot", "gmail", "slack", "n8n"}
_OPERATIONS = {
    "structured_generation",
    "intake",
    "notification_outcome",
    "ODOO_LOOKUP",
    "ODOO_BRIDGE",
    "HUBSPOT_COMPANY",
    "HUBSPOT_DEAL",
    "HUBSPOT_ASSOCIATION",
}
_STATES = {
    "SUCCESS",
    "FAILURE",
    "UNAVAILABLE",
    "RECORDED",
    "PROCESSING",
    "NEEDS_REVIEW",
    "READY_FOR_APPROVAL",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "DELIVERED",
    "PENDING",
    "CLAIMED",
    "NOT_OBSERVED",
    "RECEIVED",
    "EXTRACTED",
    "VALIDATED",
    "APPROVED",
    "SYNCING",
    "COMPLETED",
    "REJECTED",
    "UNKNOWN",
}
_FAILURE_CODES = {
    "PROVIDER_TIMEOUT",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_ERROR",
    "INTEGRATION_CONFIG",
    "PROVIDER_RATE_LIMIT",
    "PROVIDER_INVALID_RESPONSE",
    "PROVIDER_PENDING",
    "PROVIDER_REJECTED",
    "TRUSTED_CUSTOMER_MISSING",
    "TRUSTED_CUSTOMER_AMBIGUOUS",
    "TRUSTED_PRODUCT_MISSING",
    "TRUSTED_PRODUCT_CHANGED",
    "INVENTORY_INSUFFICIENT",
    "WORKER_LEASE_EXHAUSTED",
    "IDEMPOTENCY_CONFLICT",
    "RECONCILIATION_REQUIRED",
    "NOTIFICATION_FAILURE",
    "RATE_LIMITED",
    "AUTHENTICATION_FAILED",
    "PERMISSION_DENIED",
    "TARGET_NOT_FOUND",
    "TIMEOUT",
    "DELIVERY_REJECTED",
    "UNKNOWN_FAILURE",
}


class StructuredEventLogger:
    """Serialize only the bounded fields explicitly supported by M10D."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("opsflow.observability")

    def emit(
        self,
        *,
        event: str,
        level: int = logging.INFO,
        request_id: str | None = None,
        workflow_execution_id: str | None = None,
        order_id: str | None = None,
        provider: str | None = None,
        operation: str | None = None,
        failure_code: str | None = None,
        state: str | None = None,
        attempt: int | None = None,
        duration_ms: float | None = None,
        http_method: str | None = None,
        route: str | None = None,
        status_code: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        """Best-effort emit of one fixed-shape JSON event."""

        try:
            if event not in _EVENTS:
                return
            record: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": logging.getLevelName(level),
                "event": event,
            }
            normalized_request = normalize_request_id(request_id)
            normalized_workflow = normalize_workflow_execution_id(workflow_execution_id)
            if normalized_request is not None:
                record["request_id"] = normalized_request
            if normalized_workflow is not None:
                record["workflow_execution_id"] = normalized_workflow
            if order_id is not None and _is_uuid(order_id):
                record["order_id"] = order_id
            if provider in _PROVIDERS:
                record["provider"] = provider
            if operation in _OPERATIONS:
                record["operation"] = operation
            if failure_code is not None:
                record["failure_code"] = (
                    failure_code if failure_code in _FAILURE_CODES else "UNKNOWN_FAILURE"
                )
            if state is not None:
                record["state"] = state if state in _STATES else "UNKNOWN"
            if type(attempt) is int and 0 <= attempt <= 1000:
                record["attempt"] = attempt
            if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
                record["duration_ms"] = round(min(float(duration_ms), 86_400_000), 3)
            if http_method in {"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}:
                record["http_method"] = http_method
            if route is not None and _SAFE_VALUE.fullmatch(route):
                record["route"] = route[:256]
            if type(status_code) is int and 100 <= status_code <= 599:
                record["status_code"] = status_code
            for name, value in (
                ("input_tokens", input_tokens),
                ("output_tokens", output_tokens),
                ("total_tokens", total_tokens),
            ):
                if type(value) is int and 0 <= value <= 2_147_483_647:
                    record[name] = value
            self._logger.log(level, json.dumps(record, separators=(",", ":"), sort_keys=True))
        except Exception:
            # Diagnostics must never alter the business path.
            return


__all__ = ["StructuredEventLogger"]


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (AttributeError, ValueError):
        return False
    return True
