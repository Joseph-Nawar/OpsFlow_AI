"""Passive last-observed integration health state."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

_INTEGRATIONS = ("gemini", "odoo", "hubspot", "gmail", "slack", "n8n")
_CONFIGURATION = {"CONFIGURED", "UNCONFIGURED", "EXTERNALLY_MANAGED"}
_OBSERVATIONS = {"NOT_OBSERVED", "HEALTHY", "UNAVAILABLE"}


class IntegrationHealthRegistry:
    """Store only fixed integration metadata and explicit real-operation outcomes."""

    def __init__(self, configuration: dict[str, str]) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, dict[str, str | None]] = {
            name: {
                "configuration": configuration.get(name, "UNCONFIGURED")
                if configuration.get(name, "UNCONFIGURED") in _CONFIGURATION
                else "UNCONFIGURED",
                "observation": "NOT_OBSERVED",
                "last_observed_at": None,
                "failure_code": None,
            }
            for name in _INTEGRATIONS
        }

    def observe_success(self, integration: str) -> None:
        self._observe(integration, "HEALTHY", None)

    def observe_failure(self, integration: str, failure_code: str) -> None:
        bounded_code = failure_code if _safe_code(failure_code) else "UNKNOWN_FAILURE"
        self._observe(integration, "UNAVAILABLE", bounded_code)

    def snapshot(self) -> dict[str, dict[str, str | None]]:
        with self._lock:
            return {name: dict(record) for name, record in self._records.items()}

    def _observe(self, integration: str, observation: str, failure_code: str | None) -> None:
        if integration not in self._records or observation not in _OBSERVATIONS:
            return
        with self._lock:
            record = self._records[integration]
            record["observation"] = observation
            record["last_observed_at"] = datetime.now(UTC).isoformat()
            record["failure_code"] = failure_code


def _safe_code(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value.replace("_", "").isalnum()
        and value.upper() == value
    )


__all__ = ["IntegrationHealthRegistry"]
