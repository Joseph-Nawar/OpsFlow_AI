"""Small synchronized process-local counters and fixed-bucket histograms."""

from __future__ import annotations

import re
import threading
from collections import defaultdict
from collections.abc import Mapping
from typing import cast

_BUCKETS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
_METRIC_NAMES = {
    "http_requests_total",
    "http_request_duration_ms",
    "intake_outcomes_total",
    "intake_duration_ms",
    "provider_calls_total",
    "provider_duration_ms",
    "notification_outcomes_total",
    "order_sync_steps_total",
}
_LABELS = {
    "route",
    "status_class",
    "status_code",
    "provider",
    "operation",
    "state",
    "retry_outcome",
    "channel",
    "step",
    "failure_code",
}
_MAX_LABEL_LENGTH = 128
_UUID_SEGMENT = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class MetricsRegistry:
    """Bounded metrics registry with reset-on-process-restart semantics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[str, int]] = defaultdict(dict)
        self._histograms: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)

    def increment(self, name: str, *, labels: Mapping[str, object] | None = None) -> None:
        if name not in _METRIC_NAMES:
            return
        key = _label_key(labels)
        with self._lock:
            series = self._counters[name]
            series[key] = series.get(key, 0) + 1

    def observe(
        self,
        name: str,
        value_ms: float,
        *,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        if name not in _METRIC_NAMES or not isinstance(value_ms, (int, float)):
            return
        bounded = round(max(0.0, min(float(value_ms), 86_400_000.0)), 3)
        key = _label_key(labels)
        with self._lock:
            histogram = self._histograms[name].setdefault(
                key,
                {"count": 0, "sum_ms": 0.0, "buckets": {str(bucket): 0 for bucket in _BUCKETS}},
            )
            count = cast(int, histogram["count"])
            total = cast(float, histogram["sum_ms"])
            buckets = cast(dict[str, int], histogram["buckets"])
            histogram["count"] = count + 1
            histogram["sum_ms"] = round(total + bounded, 3)
            for bucket in _BUCKETS:
                if bounded <= bucket:
                    buckets[str(bucket)] += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = {name: dict(series) for name, series in self._counters.items()}
            histograms = {
                name: {
                    key: {
                        "count": cast(int, value["count"]),
                        "sum_ms": cast(float, value["sum_ms"]),
                        "buckets": dict(cast(dict[str, int], value["buckets"])),
                    }
                    for key, value in series.items()
                }
                for name, series in self._histograms.items()
            }
        return {"counters": counters, "histograms": histograms}


def _label_key(labels: Mapping[str, object] | None) -> str:
    if not labels:
        return "__all__"
    safe: list[tuple[str, str]] = []
    for key, value in sorted(labels.items()):
        if key not in _LABELS:
            continue
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            continue
        rendered = str(value)
        if not 1 <= len(rendered) <= _MAX_LABEL_LENGTH:
            continue
        if key == "route" and _UUID_SEGMENT.search(rendered):
            continue
        if key in {
            "route",
            "provider",
            "operation",
            "state",
            "retry_outcome",
            "channel",
            "step",
            "failure_code",
            "status_class",
        } and any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./:{}-"
            for character in rendered
        ):
            continue
        safe.append((key, rendered))
    return ",".join(f"{key}={value}" for key, value in safe) or "__all__"


__all__ = ["MetricsRegistry"]
