"""Comparison invariants for Phase 11 evaluation runs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from .models import EvaluationMode, EvaluationRunResult, LatencyMetrics, TimingMetric

_REQUIRED_GATES = {
    "invalid_orders_executed_zero",
    "deterministic_violation_routing_100",
    "duplicate_blocking_100",
    "malformed_security_safe_100",
    "direct_llm_side_effects_zero",
}
_PYTHON_VERSION = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?$")
_POSTGRES_VERSION = re.compile(r"^PostgreSQL\s+(\d+)(?:\.\d+)?\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Whether two runs provide comparable correctness and latency evidence."""

    correctness_comparable: bool
    latency_comparable: bool
    invariant_mismatches: tuple[str, ...]
    latency_limitation: str | None
    baseline_git_sha: str
    candidate_git_sha: str

    def require_optimization_claim(self) -> None:
        """Reject an optimization claim unless correctness and latency are comparable."""

        if not self.correctness_comparable:
            raise ValueError("optimization claims require passing comparable correctness evidence")
        if not self.latency_comparable:
            raise ValueError("optimization claims require comparable latency evidence")


def _passing_gate_evidence(run: EvaluationRunResult) -> bool:
    summary = run.release_gates
    gates = summary.results
    gate_ids = tuple(gate.gate_id for gate in gates)
    if summary.all_passed is not True or set(gate_ids) != _REQUIRED_GATES:
        return False
    if len(gate_ids) != len(_REQUIRED_GATES):
        return False

    for gate in gates:
        if (
            gate.status != "PASS"
            or gate.failing_case_ids
            or gate.numerator is None
            or gate.denominator is None
            or gate.denominator == 0
        ):
            return False
        if gate.gate_id in {"invalid_orders_executed_zero", "direct_llm_side_effects_zero"}:
            if gate.numerator != 0:
                return False
        elif gate.numerator != gate.denominator:
            return False
        if (
            gate.gate_id == "direct_llm_side_effects_zero"
            and gate.denominator != run.corpus.case_count
        ):
            return False
    return True


def _case_evidence_is_complete(run: EvaluationRunResult) -> bool:
    case_ids = tuple(case.case_id for case in run.cases)
    return not (
        run.corpus.case_count != len(run.cases)
        or len(case_ids) != len(set(case_ids))
        or any(case.status != "PASS" for case in run.cases)
    )


def _cost_is_compared(baseline: EvaluationRunResult, candidate: EvaluationRunResult) -> bool:
    return any(
        run.metrics.cost.status == "AVAILABLE"
        or run.metrics.cost.estimated_model_cost_per_initial_order is not None
        for run in (baseline, candidate)
    )


def _database_version_family(value: str | None) -> str | None:
    if value is None:
        return None
    match = _POSTGRES_VERSION.match(value)
    return f"postgresql-{match.group(1)}" if match is not None else None


def _valid_timing(metric: TimingMetric) -> bool:
    try:
        TimingMetric.model_validate(metric.model_dump())
    except ValidationError:
        return False
    return True


def compare_runs(
    baseline: EvaluationRunResult,
    candidate: EvaluationRunResult,
) -> ComparisonResult:
    """Compare runs against the Phase 11 correctness, safety, and latency contract."""

    mismatches: list[str] = []

    def correctness_mismatch(invariant: str) -> None:
        mismatches.append(f"correctness:{invariant}")

    def latency_mismatch(invariant: str) -> None:
        mismatches.append(f"latency:{invariant}")

    if baseline.schema_version != candidate.schema_version:
        correctness_mismatch("result_schema")
    if baseline.evaluation_version != candidate.evaluation_version:
        correctness_mismatch("evaluation_contract")
    if baseline.run.corpus_version != candidate.run.corpus_version:
        correctness_mismatch("corpus_version")
    if baseline.corpus != candidate.corpus:
        correctness_mismatch("corpus_composition")
    if baseline.run.mode != candidate.run.mode:
        correctness_mismatch("evaluation_mode")
    if baseline.run.command != candidate.run.command:
        correctness_mismatch("evaluation_command")

    baseline_case_ids = tuple(case.case_id for case in baseline.cases)
    candidate_case_ids = tuple(case.case_id for case in candidate.cases)
    if (
        len(baseline_case_ids) != len(set(baseline_case_ids))
        or len(candidate_case_ids) != len(set(candidate_case_ids))
        or set(baseline_case_ids) != set(candidate_case_ids)
    ):
        correctness_mismatch("case_identities")
    if not _case_evidence_is_complete(baseline) or not _case_evidence_is_complete(candidate):
        correctness_mismatch("case_outcomes")

    baseline_gates = {gate.gate_id: gate for gate in baseline.release_gates.results}
    candidate_gates = {gate.gate_id: gate for gate in candidate.release_gates.results}
    if (
        not _passing_gate_evidence(baseline)
        or not _passing_gate_evidence(candidate)
        or set(baseline_gates) != set(candidate_gates)
        or any(
            baseline_gates[gate_id].denominator != candidate_gates[gate_id].denominator
            for gate_id in baseline_gates.keys() & candidate_gates.keys()
        )
    ):
        correctness_mismatch("release_gate_evidence")

    if baseline.run.mode == EvaluationMode.LIVE_GEMINI:
        baseline_model = baseline.run.gemini_model
        candidate_model = candidate.run.gemini_model
        if not baseline_model or baseline_model != candidate_model:
            correctness_mismatch("gemini_model")
        if _cost_is_compared(baseline, candidate):
            baseline_pricing = baseline.pricing
            candidate_pricing = candidate.pricing
            if (
                baseline_pricing.status != "AVAILABLE"
                or candidate_pricing.status != "AVAILABLE"
                or not baseline_pricing.pricing_snapshot_id
                or baseline_pricing.pricing_snapshot_id != candidate_pricing.pricing_snapshot_id
                or baseline_pricing.model != baseline_model
                or candidate_pricing.model != candidate_model
            ):
                correctness_mismatch("live_cost_pricing_snapshot")

    correctness_comparable = not any(mismatch.startswith("correctness:") for mismatch in mismatches)

    baseline_python = _PYTHON_VERSION.fullmatch(baseline.run.python_version or "")
    candidate_python = _PYTHON_VERSION.fullmatch(candidate.run.python_version or "")
    if (
        baseline_python is None
        or candidate_python is None
        or baseline_python.groups() != candidate_python.groups()
    ):
        latency_mismatch("python_major_minor")
    if (
        not baseline.run.dependency_lock_identity
        or baseline.run.dependency_lock_identity != candidate.run.dependency_lock_identity
    ):
        latency_mismatch("dependency_lock")
    if not baseline.run.platform or baseline.run.platform != candidate.run.platform:
        latency_mismatch("platform")
    if (
        not baseline.run.cpu_architecture
        or baseline.run.cpu_architecture != candidate.run.cpu_architecture
    ):
        latency_mismatch("cpu_architecture")
    if (
        baseline.run.database.engine != "postgresql"
        or candidate.run.database.engine != "postgresql"
        or not baseline.run.database.isolated
        or not candidate.run.database.isolated
        or _database_version_family(baseline.run.database_version)
        != _database_version_family(candidate.run.database_version)
        or _database_version_family(baseline.run.database_version) is None
    ):
        latency_mismatch("database_engine_or_version_family")

    baseline_latency = baseline.metrics.latency
    candidate_latency = candidate.metrics.latency
    if set(LatencyMetrics.model_fields) != set(baseline_latency.model_fields_set) or set(
        LatencyMetrics.model_fields
    ) != set(candidate_latency.model_fields_set):
        latency_mismatch("timing_stage_evidence")
    for stage in LatencyMetrics.model_fields:
        baseline_metric = getattr(baseline_latency, stage)
        candidate_metric = getattr(candidate_latency, stage)
        if not _valid_timing(baseline_metric) or not _valid_timing(candidate_metric):
            latency_mismatch(f"invalid_timing_evidence:{stage}")
            continue
        if (
            baseline_metric.percentile_method != "nearest_rank_no_interpolation"
            or candidate_metric.percentile_method != "nearest_rank_no_interpolation"
            or baseline_metric.percentile_method != candidate_metric.percentile_method
        ):
            latency_mismatch(f"percentile_method:{stage}")
        if (baseline_metric.sample_count == 0) != (candidate_metric.sample_count == 0):
            latency_mismatch(f"sample_availability:{stage}")

    if not correctness_comparable:
        latency_mismatch("correctness_evidence_not_comparable")

    latency_mismatches = tuple(
        mismatch for mismatch in mismatches if mismatch.startswith("latency:")
    )
    return ComparisonResult(
        correctness_comparable=correctness_comparable,
        latency_comparable=not latency_mismatches,
        invariant_mismatches=tuple(mismatches),
        latency_limitation="; ".join(latency_mismatches) if latency_mismatches else None,
        baseline_git_sha=baseline.run.git_sha,
        candidate_git_sha=candidate.run.git_sha,
    )
