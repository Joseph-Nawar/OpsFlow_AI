"""Validate and compare Phase 11 evaluation evidence."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from opsflow.domain.order import OrderState

from .corpus import load_manifest
from .models import (
    CaseResult,
    CaseResultStatus,
    CorpusCase,
    CorpusComposition,
    CorpusManifest,
    EvaluationMode,
    EvaluationRunResult,
    LatencyMetrics,
    ReleaseGateSummary,
    RoutingMetrics,
    TimingMetric,
)
from .scoring import (
    build_routing_metrics,
    evaluate_release_gates,
    logical_object_observation_facts,
    score_execution_safety_outcome,
    score_reliability_outcome,
    score_replay_outcome,
    score_validation_outcome,
)

_PYTHON_VERSION = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?$")
_POSTGRES_VERSION = re.compile(r"^PostgreSQL\s+(\d+)(?:\.\d+)?\b", re.IGNORECASE)
_TIMING_TOLERANCE_MS = Decimal("0.000000001")
# Task 8's complete-corpus stage populations are specific to corpus 3.0.0.
# Live Gemini calls vary by reached case and attempt, so they are verified against attribution.
_PROVIDER_FREE_SAMPLES = {
    "parse_ms": 38,
    "deterministic_validation_ms": 35,
    "provider_free_intake_ms": 30,
    "provider_free_replay_intake_ms": 8,
    "provider_free_recovery_intake_ms": 4,
    "live_gemini_call_ms": 0,
}
_LIVE_SAMPLES = {
    "parse_ms": 38,
    "deterministic_validation_ms": 35,
    "provider_free_intake_ms": 0,
    "provider_free_replay_intake_ms": 8,
    "provider_free_recovery_intake_ms": 4,
}
_COMPARISON_PERCENTILES = ("p50_ms", "p95_ms")


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Evidence validity, experiment comparability, outcomes, and claim eligibility."""

    correctness_comparable: bool
    latency_comparable: bool
    invariant_mismatches: tuple[str, ...]
    latency_limitation: str | None
    baseline_git_sha: str
    candidate_git_sha: str
    baseline_evidence_valid: bool
    candidate_evidence_valid: bool
    baseline_correctness_passed: bool | None
    candidate_correctness_passed: bool | None
    optimization_eligible: bool
    improved_latency_metrics: tuple[str, ...]

    def require_optimization_claim(
        self,
        *,
        stage: str,
        percentile: Literal["p50_ms", "p95_ms"],
    ) -> None:
        """Require sound passing runs and an observed decrease in the named metric.

        This establishes that the named latency observation moved in the claimed
        direction. It does not establish causation, statistical significance, or
        a production SLA.
        """

        if not self.baseline_evidence_valid or not self.candidate_evidence_valid:
            raise ValueError("optimization claims require valid baseline and candidate evidence")
        if not self.correctness_comparable:
            raise ValueError("optimization claims require comparable correctness evidence")
        if self.baseline_correctness_passed is not True:
            raise ValueError("optimization claims require a passing baseline correctness outcome")
        if self.candidate_correctness_passed is not True:
            raise ValueError("optimization claims require a passing candidate correctness outcome")
        if not self.latency_comparable:
            raise ValueError("optimization claims require comparable latency evidence")
        metric = f"{stage}:{percentile}"
        if metric not in self.improved_latency_metrics:
            raise ValueError("no observed latency improvement is supported for the named metric")


def _database_version_family(value: str | None) -> str | None:
    if value is None:
        return None
    match = _POSTGRES_VERSION.match(value)
    return f"postgresql-{match.group(1)}" if match is not None else None


def _canonical_corpus_path() -> Path:
    return Path(__file__).resolve().parents[3] / "evals/corpus/v1"


def _composition_from_manifest(manifest: CorpusManifest) -> CorpusComposition:
    categories = Counter(case.primary_category for case in manifest.cases)
    formats = Counter(case.source.document_type for case in manifest.cases)
    tags = Counter(tag for case in manifest.cases for tag in case.tags)
    return CorpusComposition(
        case_count=len(manifest.cases),
        primary_category_counts=dict(categories),
        format_counts=dict(formats),
        tag_counts=dict(tags),
    )


def _valid_timing(metric: TimingMetric) -> bool:
    """Check all arithmetic constraints recoverable from aggregate samples."""

    try:
        value = TimingMetric.model_validate(metric.model_dump())
    except ValidationError:
        return False

    if value.sample_count == 0:
        return True

    minimum = value.minimum_ms
    maximum = value.maximum_ms
    total = value.sum_ms
    p50 = value.p50_ms
    p95 = value.p95_ms
    if None in (minimum, maximum, total, p50, p95):
        return False
    assert minimum is not None and maximum is not None and total is not None
    assert p50 is not None and p95 is not None

    if not minimum <= p50 <= p95 <= maximum:
        return False
    count = Decimal(value.sample_count)
    if value.sample_count == 1:
        return minimum == maximum == total == p50 == p95
    lower_bound = maximum + (count - 1) * minimum
    upper_bound = minimum + (count - 1) * maximum
    return (
        total + _TIMING_TOLERANCE_MS >= lower_bound and total - _TIMING_TOLERANCE_MS <= upper_bound
    )


def _side_effects_are_observed(result: CaseResult) -> bool:
    return all(
        detail.status is not None and detail.count is not None
        for detail in (
            result.side_effects.order_sync,
            result.side_effects.logical_external_objects,
        )
    )


def _replay_observations_complete(result: CaseResult) -> bool:
    replay = result.actual.replay
    required_values = (
        None if replay is None else replay.creation_disposition,
        None if replay is None else replay.intake_execution,
        None if replay is None else replay.seed_order_id,
        None if replay is None else replay.replay_order_id,
        None if replay is None else replay.authoritative_order_count,
        None if replay is None else replay.provider_calls_before,
        None if replay is None else replay.provider_calls_after,
        None if replay is None else replay.notification_intents_before,
        None if replay is None else replay.notification_intents_after,
        None if replay is None else replay.order_sync_intents_before,
        None if replay is None else replay.order_sync_intents_after,
        None if replay is None else replay.logical_external_object_count,
        None if replay is None else replay.provider_work_stood_down,
        result.actual.order_id,
    )
    return (
        all(value is not None for value in required_values)
        and logical_object_observation_facts(result.actual.logical_objects) is not None
        and _side_effects_are_observed(result)
    )


def _recovery_observations_complete(
    case: CorpusCase,
    result: CaseResult,
    supplied_recovery_fields: frozenset[str],
) -> bool:
    recovery = result.actual.recovery
    required_fields = {
        "injected_stage",
        "failure_code",
        "failed_state",
        "failure_origin",
        "retry_used",
        "retry_generation_before",
        "retry_generation",
        "final_state",
        "receipt_count",
        "prior_receipt_ids",
        "receipt_ids_at_retry",
        "receipt_ids",
        "prior_receipts_preserved",
        "receipt_preservation_status",
    }
    if case.recovery is not None and case.recovery.injected_stage.value == "SYNCING":
        required_fields.add("resumed_sync_steps")
    if recovery is None or not required_fields.issubset(supplied_recovery_fields):
        return False
    if any(
        value is None
        for value in (
            recovery.injected_stage,
            recovery.failure_code,
            recovery.failed_state,
            recovery.failure_origin,
            recovery.retry_used,
            recovery.final_state,
            recovery.receipt_count,
            recovery.receipt_preservation_status,
        )
    ):
        return False
    injected_stage = case.recovery.injected_stage if case.recovery is not None else None
    if injected_stage is None:
        return False
    if injected_stage.value == "SYNCING":
        return (
            recovery.retry_generation_before is not None
            and recovery.retry_generation is not None
            and result.actual.external_execution is not None
            and result.actual.external_execution_eligible is not None
            and logical_object_observation_facts(result.actual.logical_objects) is not None
            and _side_effects_are_observed(result)
            and recovery.prior_receipts_preserved is not None
        )
    return (
        result.actual.idempotent_replay is not None
        and result.actual.pre_approval_state is not None
        and (
            recovery.prior_receipts_preserved is not None
            or (
                not recovery.prior_receipt_ids
                and recovery.receipt_preservation_status == "NO_PRIOR_RECEIPTS"
                and recovery.prior_receipts_preserved is None
            )
        )
    )


def _recovery_observation_issues(
    case: CorpusCase,
    result: CaseResult,
    supplied_recovery_fields: frozenset[str],
) -> list[str]:
    recovery = result.actual.recovery
    if recovery is None or case.recovery is None:
        return []

    issues: list[str] = []
    receipt_ids_observed = {
        "prior_receipt_ids",
        "receipt_ids_at_retry",
        "receipt_ids",
    }.issubset(supplied_recovery_fields)
    if (
        recovery.receipt_count is not None
        and "receipt_ids" in supplied_recovery_fields
        and recovery.receipt_count != len(recovery.receipt_ids)
    ):
        issues.append(f"recovery_receipt_count_disagrees_with_identities:{result.case_id}")

    if receipt_ids_observed:
        prior = recovery.prior_receipt_ids
        at_retry = recovery.receipt_ids_at_retry
        final = recovery.receipt_ids
        if case.recovery is not None:
            if case.recovery.injected_stage.value == "SYNCING":
                if not prior:
                    expected_status = "NO_PRIOR_RECEIPTS"
                elif not at_retry or not final:
                    expected_status = "LOST"
                elif prior != at_retry or prior != final:
                    expected_status = "REPLACED"
                else:
                    expected_status = "PRESERVED"
                expected_preserved = expected_status == "PRESERVED"
            else:
                if at_retry != final:
                    issues.append(f"recovery_receipt_snapshots_disagree:{result.case_id}")
                if not prior and not final:
                    expected_status = "NO_PRIOR_RECEIPTS"
                    expected_preserved = None
                elif not prior:
                    expected_status = "UNEXPECTED_RECEIPTS"
                    expected_preserved = False
                elif not final:
                    expected_status = "LOST"
                    expected_preserved = False
                elif prior != final:
                    expected_status = "REPLACED"
                    expected_preserved = False
                else:
                    expected_status = "PRESERVED"
                    expected_preserved = True

            if (
                recovery.receipt_preservation_status is not None
                and recovery.receipt_preservation_status != expected_status
            ):
                issues.append(f"recovery_receipt_status_disagrees_with_identities:{result.case_id}")
            if (
                recovery.prior_receipts_preserved is not None
                and recovery.prior_receipts_preserved is not expected_preserved
            ):
                issues.append(f"recovery_receipt_flag_disagrees_with_identities:{result.case_id}")
    elif result.status is not CaseResultStatus.ERROR:
        issues.append(f"recovery_receipt_identities_unavailable:{result.case_id}")

    if result.status is not CaseResultStatus.ERROR and not _recovery_observations_complete(
        case, result, supplied_recovery_fields
    ):
        issues.append(f"recovery_observations_incomplete:{result.case_id}")
    return issues


def _execution_observations_complete(
    case: CorpusCase,
    result: CaseResult,
    supplied_recovery_fields: frozenset[str],
) -> bool:
    if case.recovery is not None and case.recovery.injected_stage.value == "SYNCING":
        return _recovery_observations_complete(case, result, supplied_recovery_fields)
    return (
        result.actual.pre_approval_state is not None
        and result.actual.external_execution is not None
        and result.actual.external_execution_eligible is not None
        and logical_object_observation_facts(result.actual.logical_objects) is not None
        and _side_effects_are_observed(result)
    )


def _replay_observation_issues(case: CorpusCase, result: CaseResult) -> list[str]:
    replay = result.actual.replay
    if replay is None:
        return []
    issues: list[str] = []
    if replay.provider_calls_before is not None and replay.provider_calls_after is not None:
        derived_stood_down = replay.provider_calls_before == replay.provider_calls_after
        if (
            replay.provider_work_stood_down is not None
            and replay.provider_work_stood_down is not derived_stood_down
        ):
            issues.append(f"replay_provider_work_flag_disagrees_with_counts:{result.case_id}")
    if (
        case.replay is not None
        and result.status is not CaseResultStatus.ERROR
        and not _replay_observations_complete(result)
    ):
        issues.append(f"replay_observations_incomplete:{result.case_id}")
    return issues


def _execution_eligibility_issues(case: CorpusCase, result: CaseResult) -> list[str]:
    if case.recovery is not None and case.recovery.injected_stage.value == "SYNCING":
        return []
    state = result.actual.pre_approval_state
    eligible = result.actual.external_execution_eligible
    if state is None or eligible is None:
        return []
    derived_eligibility = state in {
        OrderState.APPROVED,
        OrderState.SYNCING,
        OrderState.COMPLETED,
    }
    if eligible is derived_eligibility:
        return []
    return [f"execution_eligibility_disagrees_with_order_state:{result.case_id}"]


def _case_evidence_issues(run: EvaluationRunResult, manifest: CorpusManifest) -> list[str]:
    issues: list[str] = []
    supplied_recovery_fields = {
        case.case_id: (
            frozenset(case.actual.recovery.model_fields_set)
            if case.actual.recovery is not None
            else frozenset()
        )
        for case in run.cases
    }
    try:
        cases = tuple(
            CaseResult.model_validate(case.model_dump(mode="python")) for case in run.cases
        )
        CorpusComposition.model_validate(run.corpus.model_dump())
        ReleaseGateSummary.model_validate(run.release_gates.model_dump())
        RoutingMetrics.model_validate(run.metrics.routing.model_dump())
    except ValidationError:
        return ["result_contract"]
    if run.run.corpus_version != manifest.corpus_version:
        issues.append("corpus_version_not_verified_against_manifest")
    if run.run.mode is EvaluationMode.PROVIDER_FREE:
        cost = run.metrics.cost
        if (
            run.run.gemini_model is not None
            or any(case.provider.name == "gemini" for case in cases)
            or run.pricing.status != "NOT_APPLICABLE"
            or run.pricing.pricing_snapshot_id is not None
            or run.pricing.model is not None
            or cost.status != "NOT_APPLICABLE"
            or cost.estimated_model_cost_per_initial_order is not None
            or cost.gemini_called_order_count != 0
        ):
            issues.append("provider_free_run_contains_live_evidence")
    elif run.run.gemini_model is None:
        issues.append("live_run_missing_configured_model")
    case_ids = tuple(case.case_id for case in cases)
    manifest_ids = tuple(case.case_id for case in manifest.cases)
    if len(case_ids) != len(set(case_ids)):
        issues.append("duplicate_case_identities")
    if len(cases) != len(manifest.cases) or set(case_ids) != set(manifest_ids):
        issues.append("case_identities_do_not_match_corpus")
    if run.corpus != _composition_from_manifest(manifest):
        issues.append("corpus_composition")

    by_id = {case.case_id: case for case in cases}
    for corpus_case in manifest.cases:
        result = by_id.get(corpus_case.case_id)
        if result is None:
            continue
        actual = result.actual
        validation_observations_complete = corpus_case.expected_validation is None or (
            actual.route is not None and actual.pre_approval_state is not None
        )
        if not validation_observations_complete:
            if result.status is not CaseResultStatus.ERROR:
                issues.append(f"validation_observations_incomplete:{result.case_id}")
            expected_validation_match = None
        else:
            validation_score = score_validation_outcome(corpus_case.expected_validation, result)
            expected_validation_match = (
                validation_score.overall_match if validation_score is not None else None
            )
        recovery_fields = supplied_recovery_fields.get(result.case_id, frozenset())
        issues.extend(_replay_observation_issues(corpus_case, result))
        expected_replay_match = (
            score_replay_outcome(corpus_case, result)
            if corpus_case.replay is None or _replay_observations_complete(result)
            else None
        )
        issues.extend(_recovery_observation_issues(corpus_case, result, recovery_fields))
        expected_reliability_match = (
            score_reliability_outcome(corpus_case, result)
            if corpus_case.recovery is None
            or _recovery_observations_complete(corpus_case, result, recovery_fields)
            else None
        )
        execution_observations_complete = _execution_observations_complete(
            corpus_case, result, recovery_fields
        )
        issues.extend(_execution_eligibility_issues(corpus_case, result))
        if not execution_observations_complete and result.status is not CaseResultStatus.ERROR:
            issues.append(f"execution_safety_observations_incomplete:{result.case_id}")
        expected_execution_safety_match = (
            score_execution_safety_outcome(corpus_case, result)
            if execution_observations_complete
            else None
        )
        expected_scores = {
            "extraction_exact_match": None,
            "validation_match": expected_validation_match,
            "reliability_match": expected_reliability_match,
            "replay_match": expected_replay_match,
            "execution_safety_match": expected_execution_safety_match,
        }
        required_scores = {
            "validation_match": corpus_case.expected_validation is not None,
            "reliability_match": corpus_case.recovery is not None,
            "replay_match": corpus_case.replay is not None,
            "execution_safety_match": True,
        }
        for field, expected_score in expected_scores.items():
            if getattr(result.scores, field) is not expected_score:
                issues.append(f"{field}_disagrees_with_observation:{result.case_id}")
            if (
                field in required_scores
                and required_scores[field]
                and expected_score is None
                and result.status is not CaseResultStatus.ERROR
            ):
                issues.append(f"{field}_evidence_unavailable:{result.case_id}")

        logical_facts = logical_object_observation_facts(actual.logical_objects)
        if actual.logical_objects is not None and logical_facts is None:
            issues.append(f"logical_object_observations_incomplete:{result.case_id}")
        elif logical_facts is not None:
            _duplication_count, extra_object, completed_step_rerun, executor_reached = logical_facts
            if actual.logical_objects is not None and (
                actual.logical_objects.replay_created_extra_object is not extra_object
                or actual.logical_objects.completed_step_rerun is not completed_step_rerun
                or actual.logical_objects.executor_reached is not executor_reached
            ):
                issues.append(f"logical_object_flags_disagree_with_observations:{result.case_id}")

        has_failed_score = any(value is False for value in expected_scores.values())
        if result.status == CaseResultStatus.PASS and has_failed_score:
            issues.append(f"pass_case_has_failed_score:{result.case_id}")
        if result.status == CaseResultStatus.FAIL and not has_failed_score:
            issues.append(f"failed_case_has_no_failed_score:{result.case_id}")

    gates = evaluate_release_gates(manifest, cases)
    if gates != run.release_gates:
        issues.append("release_gates_disagree_with_case_observations")
    routing = build_routing_metrics(manifest, cases, gates)
    if routing != run.metrics.routing:
        issues.append("routing_metrics_disagree_with_case_observations")
    return issues


def _timing_issues(run: EvaluationRunResult, manifest: CorpusManifest) -> list[str]:
    """Validate current 3.0.0 stage coverage without generalizing it to future corpora."""

    issues: list[str] = []
    latency = run.metrics.latency
    if set(LatencyMetrics.model_fields) != set(latency.model_fields_set):
        issues.append("missing_timing_stage_evidence")

    for stage in LatencyMetrics.model_fields:
        if not _valid_timing(getattr(latency, stage)):
            issues.append(f"invalid_timing_summary:{stage}")

    if manifest.corpus_version != "3.0.0" or len(manifest.cases) != 36:
        issues.append("unsupported_timing_population_contract")
        return issues

    if run.run.mode is EvaluationMode.PROVIDER_FREE:
        expected = _PROVIDER_FREE_SAMPLES
    else:
        live_calls = sum(
            case.provider.calls for case in run.cases if case.provider.name == "gemini"
        )
        if live_calls != run.metrics.provider_usage.gemini_call_count:
            issues.append("gemini_call_count_disagrees_with_case_attribution")
        expected = {**_LIVE_SAMPLES, "live_gemini_call_ms": live_calls}

    for stage, count in expected.items():
        if getattr(latency, stage).sample_count != count:
            issues.append(f"incomplete_timing_population:{stage}")
    return issues


def _correctness_passed(run: EvaluationRunResult, evidence_valid: bool) -> bool | None:
    if not evidence_valid:
        return None
    return (
        run.release_gates.all_passed is True
        and all(gate.status == "PASS" for gate in run.release_gates.results)
        and all(case.status is CaseResultStatus.PASS for case in run.cases)
    )


def _cost_is_compared(baseline: EvaluationRunResult, candidate: EvaluationRunResult) -> bool:
    return any(
        run.metrics.cost.status == "AVAILABLE"
        or run.metrics.cost.estimated_model_cost_per_initial_order is not None
        for run in (baseline, candidate)
    )


def compare_runs(
    baseline: EvaluationRunResult,
    candidate: EvaluationRunResult,
) -> ComparisonResult:
    """Validate both results, compare matching dimensions, and assess claim support."""

    mismatches: list[str] = []

    def mismatch(category: str, invariant: str) -> None:
        mismatches.append(f"{category}:{invariant}")

    try:
        manifest = load_manifest(_canonical_corpus_path())
    except (OSError, ValueError):
        manifest = None

    baseline_correctness_issues = (
        ["canonical_corpus_unavailable"]
        if manifest is None
        else _case_evidence_issues(baseline, manifest)
    )
    candidate_correctness_issues = (
        ["canonical_corpus_unavailable"]
        if manifest is None
        else _case_evidence_issues(candidate, manifest)
    )
    baseline_timing_issues = (
        ["canonical_corpus_unavailable"] if manifest is None else _timing_issues(baseline, manifest)
    )
    candidate_timing_issues = (
        ["canonical_corpus_unavailable"]
        if manifest is None
        else _timing_issues(candidate, manifest)
    )
    baseline_evidence_valid = not baseline_correctness_issues and not baseline_timing_issues
    candidate_evidence_valid = not candidate_correctness_issues and not candidate_timing_issues

    for side, issues in (
        ("baseline", baseline_correctness_issues),
        ("candidate", candidate_correctness_issues),
        ("baseline", baseline_timing_issues),
        ("candidate", candidate_timing_issues),
    ):
        for issue in issues:
            mismatch(f"evidence:{side}", issue)

    correctness_invariants: list[str] = []
    if baseline.schema_version != candidate.schema_version:
        correctness_invariants.append("result_schema")
    if baseline.evaluation_version != candidate.evaluation_version:
        correctness_invariants.append("evaluation_contract")
    if baseline.run.corpus_version != candidate.run.corpus_version:
        correctness_invariants.append("corpus_version")
    if baseline.corpus != candidate.corpus:
        correctness_invariants.append("corpus_composition")
    if baseline.run.mode != candidate.run.mode:
        correctness_invariants.append("evaluation_mode")
    if baseline.run.command != candidate.run.command:
        correctness_invariants.append("evaluation_command")
    baseline_case_ids = tuple(case.case_id for case in baseline.cases)
    candidate_case_ids = tuple(case.case_id for case in candidate.cases)
    if (
        len(baseline_case_ids) != len(set(baseline_case_ids))
        or len(candidate_case_ids) != len(set(candidate_case_ids))
        or set(baseline_case_ids) != set(candidate_case_ids)
    ):
        correctness_invariants.append("case_identities")
    if baseline.run.mode is EvaluationMode.LIVE_GEMINI:
        baseline_model = baseline.run.gemini_model
        candidate_model = candidate.run.gemini_model
        if not baseline_model or baseline_model != candidate_model:
            correctness_invariants.append("gemini_model")
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
                correctness_invariants.append("live_cost_pricing_snapshot")
    for invariant in correctness_invariants:
        mismatch("correctness", invariant)

    correctness_evidence_valid = (
        not baseline_correctness_issues and not candidate_correctness_issues
    )
    correctness_comparable = correctness_evidence_valid and not correctness_invariants
    baseline_correctness_passed = _correctness_passed(baseline, not baseline_correctness_issues)
    candidate_correctness_passed = _correctness_passed(candidate, not candidate_correctness_issues)

    latency_mismatches: list[str] = []

    def latency_mismatch(invariant: str) -> None:
        latency_mismatches.append(f"latency:{invariant}")

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
    baseline_db_family = _database_version_family(baseline.run.database_version)
    candidate_db_family = _database_version_family(candidate.run.database_version)
    if (
        baseline.run.database.engine != "postgresql"
        or candidate.run.database.engine != "postgresql"
        or not baseline.run.database.isolated
        or not candidate.run.database.isolated
        or baseline_db_family is None
        or baseline_db_family != candidate_db_family
    ):
        latency_mismatch("database_engine_or_version_family")
    if baseline.run.mode is EvaluationMode.LIVE_GEMINI and (
        baseline.run.gemini_model != candidate.run.gemini_model
    ):
        latency_mismatch("gemini_model")

    baseline_latency = baseline.metrics.latency
    candidate_latency = candidate.metrics.latency
    if set(LatencyMetrics.model_fields) != set(baseline_latency.model_fields_set) or set(
        LatencyMetrics.model_fields
    ) != set(candidate_latency.model_fields_set):
        latency_mismatch("timing_stage_evidence")
    if baseline_timing_issues or candidate_timing_issues:
        latency_mismatch("invalid_or_incomplete_timing_evidence")

    improved_metrics: list[str] = []
    for stage in LatencyMetrics.model_fields:
        baseline_metric = getattr(baseline_latency, stage)
        candidate_metric = getattr(candidate_latency, stage)
        if (
            baseline_metric.percentile_method != "nearest_rank_no_interpolation"
            or candidate_metric.percentile_method != "nearest_rank_no_interpolation"
            or baseline_metric.percentile_method != candidate_metric.percentile_method
        ):
            latency_mismatch(f"percentile_method:{stage}")
            continue
        if baseline_metric.sample_count != candidate_metric.sample_count:
            latency_mismatch(f"sample_count:{stage}")
            continue
        if baseline_metric.sample_count == 0:
            continue
        for percentile in _COMPARISON_PERCENTILES:
            baseline_value = getattr(baseline_metric, percentile)
            candidate_value = getattr(candidate_metric, percentile)
            if (
                baseline_value is not None
                and candidate_value is not None
                and candidate_value < baseline_value
            ):
                improved_metrics.append(f"{stage}:{percentile}")

    if not correctness_comparable:
        latency_mismatch("correctness_evidence_not_comparable")
    for item in latency_mismatches:
        mismatches.append(item)

    latency_comparable = (
        correctness_comparable
        and not baseline_timing_issues
        and not candidate_timing_issues
        and not latency_mismatches
    )
    optimization_eligible = (
        correctness_comparable
        and latency_comparable
        and baseline_correctness_passed is True
        and candidate_correctness_passed is True
        and bool(improved_metrics)
    )
    return ComparisonResult(
        correctness_comparable=correctness_comparable,
        latency_comparable=latency_comparable,
        invariant_mismatches=tuple(mismatches),
        latency_limitation="; ".join(latency_mismatches) if latency_mismatches else None,
        baseline_git_sha=baseline.run.git_sha,
        candidate_git_sha=candidate.run.git_sha,
        baseline_evidence_valid=baseline_evidence_valid,
        candidate_evidence_valid=candidate_evidence_valid,
        baseline_correctness_passed=baseline_correctness_passed,
        candidate_correctness_passed=candidate_correctness_passed,
        optimization_eligible=optimization_eligible,
        improved_latency_metrics=tuple(sorted(improved_metrics)),
    )
