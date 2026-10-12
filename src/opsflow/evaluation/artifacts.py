"""Validated JSON artifacts and reports rendered only from their JSON source."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import EvaluationRunResult, RateMetric, TimingMetric

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "evaluation_version",
        "run",
        "corpus",
        "cases",
        "metrics",
        "pricing",
        "release_gates",
        "limitations",
    }
)
_SENSITIVE_KEY = re.compile(
    r"(?:raw|prompt|api[_ -]?key|authorization|credential|password|database[_ -]?url|"
    r"provider[_ -]?response|private[_ -]?machine|hostname|mac[_ -]?address|serial[_ -]?number)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?:bearer\s|AIza[0-9A-Za-z_-]{8,}|https?://|postgres(?:ql)?(?:\+\w+)?://|"
    r"(?:^|\s)/(?:Users|Volumes|home|private)/|traceback|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})",
    re.IGNORECASE,
)
_GATE_EXPLANATIONS = {
    "invalid_orders_executed_zero": (
        "Invalid cases must not reach approval, sync, completion, or an external executor."
    ),
    "deterministic_violation_routing_100": (
        "Deterministic violations must match the expected route, issue facts, and state."
    ),
    "duplicate_blocking_100": (
        "Duplicate replay must preserve order identity and create no additional intent or object."
    ),
    "malformed_security_safe_100": (
        "Malformed and security inputs must remain safely bounded without automatic execution."
    ),
    "direct_llm_side_effects_zero": (
        "Document and model content must not directly grant authority over side effects."
    ),
}


class ArtifactValidationError(ValueError):
    """Raised when a result artifact is malformed or not safe to publish."""


def _assert_sanitized(value: object, *, path: str = "result") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            safe_corpus_tag_count = (
                path == "result.corpus.tag_counts"
                and key_text == "prompt_injection"
                and type(item) is int
                and item >= 0
            )
            if _SENSITIVE_KEY.search(key_text) and not safe_corpus_tag_count:
                raise ArtifactValidationError(f"unsupported sensitive field at {path}.{key_text}")
            _assert_sanitized(item, path=f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_sanitized(item, path=f"{path}[{index}]")
    elif isinstance(value, str) and _SENSITIVE_VALUE.search(value):
        raise ArtifactValidationError(f"sensitive value is not allowed at {path}")


def validate_result_json(
    payload: Mapping[str, Any] | str | bytes | Path,
) -> EvaluationRunResult:
    """Parse and validate a result model from JSON text, a mapping, or a JSON path."""

    try:
        if isinstance(payload, Path):
            raw: object = json.loads(payload.read_text(encoding="utf-8"))
        elif isinstance(payload, bytes):
            raw = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            raw = json.loads(payload)
        elif isinstance(payload, Mapping):
            raw = payload
        else:
            raise TypeError("result input must be JSON text, a JSON path, or a mapping")
        if not isinstance(raw, Mapping):
            raise ArtifactValidationError("result JSON root must be an object")
        if set(raw) != _TOP_LEVEL_KEYS:
            raise ArtifactValidationError("result JSON must contain the exact v1 top-level keys")
        result = EvaluationRunResult.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, TypeError, ValidationError):
        raise ArtifactValidationError(
            "result JSON does not satisfy the evaluation result contract"
        ) from None

    serialized = result.model_dump(mode="json")
    _assert_sanitized(serialized)
    return result


def write_result_json(result: EvaluationRunResult, path: Path) -> Path:
    """Validate and atomically write the canonical structured result JSON."""

    if not isinstance(result, EvaluationRunResult):
        raise TypeError("result must be an EvaluationRunResult")
    validated = validate_result_json(result.model_dump(mode="json"))
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise ValueError("evaluation result artifacts must use a .json extension")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(validated.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_path, path)
    return path


def _display(value: object) -> str:
    if value is None:
        return "Unavailable"
    rendered = format(value, "f") if isinstance(value, Decimal) else str(value)
    if not isinstance(value, Decimal):
        rendered = (
            rendered.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\\", "\\\\")
            .replace("|", "\\|")
            .replace("`", "\\`")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("\n", " ")
            .replace("\r", " ")
        )
    return rendered


def _rate(metric: RateMetric | None) -> str:
    if metric is None:
        return "Unavailable"
    value = _display(metric.value)
    return f"{metric.numerator}/{metric.denominator} ({value})"


def _timing_row(name: str, metric: TimingMetric) -> str:
    return (
        f"| {name} | {metric.sample_count} | {_display(metric.minimum_ms)} | "
        f"{_display(metric.maximum_ms)} | {_display(metric.sum_ms)} | "
        f"{_display(metric.p50_ms)} | {_display(metric.p95_ms)} |"
    )


def render_markdown_from_json(
    payload: Mapping[str, Any] | str | bytes | Path,
) -> str:
    """Render a report from validated JSON without invoking runtime application code."""

    result = validate_result_json(payload)
    run = result.run
    metrics = result.metrics
    lines = [
        "# Phase 11 Evaluation Result",
        "",
        "## Run",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Run ID | {_display(run.run_id)} |",
        f"| Mode | {run.mode.value} |",
        f"| Git SHA | `{run.git_sha}` |",
        f"| Corpus version | {run.corpus_version} |",
        f"| Result schema | `{result.schema_version}` |",
        f"| Evaluation contract | `{result.evaluation_version}` |",
        f"| Case count | {result.corpus.case_count} |",
        f"| Started (UTC) | {run.started_at_utc.isoformat()} |",
        f"| Finished (UTC) | {run.finished_at_utc.isoformat()} |",
        f"| Platform | {_display(run.platform)} |",
        f"| Python | {_display(run.python_version)} |",
        f"| CPU architecture | {_display(run.cpu_architecture)} |",
        f"| Database | {_display(run.database_version)} |",
        "",
        "## Extraction quality",
        "",
        f"- Status: `{metrics.extraction_quality.status.value}`",
        f"- Reason: {_display(metrics.extraction_quality.reason)}",
    ]
    if metrics.extraction_quality.status.value == "NOT_APPLICABLE":
        lines.append("- Provider-free extraction contract evidence is not model accuracy.")
    else:
        lines.extend(
            [
                f"- Complete exact match: {_rate(metrics.extraction_quality.complete_exact_match)}",
                "- Field micro precision: "
                f"{_rate(metrics.extraction_quality.field_micro_precision)}",
                f"- Field micro recall: {_rate(metrics.extraction_quality.field_micro_recall)}",
                f"- Field micro F1: {_rate(metrics.extraction_quality.field_micro_f1)}",
                "- Cases reaching Gemini: "
                f"{metrics.extraction_quality.reached_live_gemini_case_count}",
            ]
        )
    lines.extend(
        [
            "",
            "## Routing and reliability",
            "",
            "| Metric | Observed |",
            "| --- | --- |",
            f"| Full routing accuracy | {_rate(metrics.routing.full_routing_accuracy)} |",
            f"| Invalid pass-through | {_rate(metrics.routing.invalid_pass_through)} |",
            f"| Duplicate blocking | {_rate(metrics.routing.duplicate_blocking)} |",
            f"| Retry recovery | {_rate(metrics.routing.retry_recovery)} |",
            f"| Malformed/security safety | {_rate(metrics.routing.malformed_security_safety)} |",
            f"| Execution safety | {_rate(metrics.routing.execution_safety)} |",
            "| Logical duplication count | "
            f"{_display(metrics.routing.logical_duplication_count)} |",
            "",
            "## Timing samples",
            "",
            "Durations are local run observations, not production latency guarantees.",
            "Percentiles use nearest-rank without interpolation.",
            "",
            "| Stage | Samples | Min ms | Max ms | Sum ms | p50 ms | p95 ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            _timing_row("Parse", metrics.latency.parse_ms),
            _timing_row("Deterministic validation", metrics.latency.deterministic_validation_ms),
            _timing_row("Provider-free intake", metrics.latency.provider_free_intake_ms),
            _timing_row(
                "Provider-free replay intake", metrics.latency.provider_free_replay_intake_ms
            ),
            _timing_row(
                "Provider-free recovery intake", metrics.latency.provider_free_recovery_intake_ms
            ),
            _timing_row("Live Gemini call", metrics.latency.live_gemini_call_ms),
            "",
            "## Provider usage and estimated model cost",
            "",
            f"- Provider usage status: `{metrics.provider_usage.status}`",
            f"- Gemini calls: {metrics.provider_usage.gemini_call_count}",
            "- Calls per initial order: "
            f"{_display(metrics.provider_usage.calls_per_initial_order)}",
            f"- Input tokens: {_display(metrics.provider_usage.input_tokens_sum)} "
            f"(available {metrics.provider_usage.available_input_token_count}; "
            f"missing {metrics.provider_usage.missing_input_token_count})",
            f"- Output tokens: {_display(metrics.provider_usage.output_tokens_sum)} "
            f"(available {metrics.provider_usage.available_output_token_count}; "
            f"missing {metrics.provider_usage.missing_output_token_count})",
            f"- Total tokens: {_display(metrics.provider_usage.total_tokens_sum)} "
            f"(available {metrics.provider_usage.available_total_token_count}; "
            f"missing {metrics.provider_usage.missing_total_token_count})",
            "- Inconsistent reported token totals: "
            f"{metrics.provider_usage.inconsistent_reported_total_count}",
            "- Calls missing initial-order attribution: "
            f"{metrics.provider_usage.missing_call_attribution_count}",
            f"- Failed provider calls: {metrics.provider_usage.failed_call_count}",
            f"- Cost status: `{metrics.cost.status}`",
            f"- Estimated model cost per initial order (USD): "
            f"{_display(metrics.cost.estimated_model_cost_per_initial_order)}",
            "- Initial orders with complete usage: "
            f"{metrics.cost.complete_usage_order_count}; incomplete: "
            f"{metrics.cost.incomplete_usage_order_count}",
            "- Zero-call initial orders: "
            f"{metrics.cost.zero_call_order_count}; Gemini-called initial orders: "
            f"{metrics.cost.gemini_called_order_count}",
            f"- Pricing status: `{result.pricing.status}`; "
            f"model: {_display(result.pricing.model)}; "
            f"snapshot: {_display(result.pricing.pricing_snapshot_id)}",
            "",
            "## Release gates",
            "",
        ]
    )
    if not result.release_gates.results:
        lines.append("No release gate results are present in this JSON result.")
    else:
        lines.extend(
            [
                f"- All gates passed: {_display(result.release_gates.all_passed)}",
                "",
                "| Gate | Result | Failing cases |",
                "| --- | --- | --- |",
            ]
        )
        for gate in result.release_gates.results:
            observed = f"{_display(gate.numerator)}/{_display(gate.denominator)}"
            failures = ", ".join(gate.failing_case_ids) if gate.failing_case_ids else "None"
            lines.append(f"| `{gate.gate_id}` | {gate.status} ({observed}) | {failures} |")
            explanation = _GATE_EXPLANATIONS.get(
                gate.gate_id,
                "The observed numerator and denominator are recorded in this result.",
            )
            lines.append(f"\n**{gate.gate_id}:** {explanation}")
    lines.extend(
        [
            "",
            "## Case outcomes",
            "",
            "| Case | Status | Route | State | Issue codes | Replay | "
            "Notification intents | Sync intents | Receipt status |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for case in result.cases:
        route = _display(case.actual.route.value if case.actual.route is not None else None)
        state = _display(
            case.actual.pre_approval_state.value if case.actual.pre_approval_state else None
        )
        issue_codes = ", ".join(code for code, _severity in case.actual.issue_facts) or "None"
        replay = case.actual.replay
        replay_value = "Unavailable"
        if replay is not None:
            replay_value = (
                f"{_display(replay.creation_disposition)} / {_display(replay.intake_execution)}"
            )
        authority = case.actual.authority
        notification_count = (
            _display(authority.notification_intent_count)
            if authority is not None
            else "Unavailable"
        )
        sync_count = (
            _display(authority.external_sync_intent_count)
            if authority is not None
            else "Unavailable"
        )
        recovery = case.actual.recovery
        receipt_status = (
            _display(recovery.receipt_preservation_status)
            if recovery is not None
            else "Unavailable"
        )
        lines.append(
            f"| `{case.case_id}` | {case.status.value} | {route} | {state} | {issue_codes} | "
            f"{replay_value} | {notification_count} | {sync_count} | {receipt_status} |"
        )
    lines.extend(["", "## Limitations", ""])
    if result.limitations:
        lines.extend(f"- {_display(limitation)}" for limitation in result.limitations)
    else:
        lines.append("- No limitations were recorded in this JSON result.")
    return "\n".join(lines) + "\n"


def write_markdown_from_json(json_path: Path, markdown_path: Path) -> Path:
    """Write a report by reading and validating only the selected JSON artifact."""

    markdown_path = Path(markdown_path)
    if markdown_path.suffix.lower() != ".md":
        raise ValueError("evaluation Markdown artifacts must use a .md extension")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        render_markdown_from_json(Path(json_path)),
        encoding="utf-8",
    )
    return markdown_path


__all__ = [
    "ArtifactValidationError",
    "render_markdown_from_json",
    "validate_result_json",
    "write_markdown_from_json",
    "write_result_json",
]
