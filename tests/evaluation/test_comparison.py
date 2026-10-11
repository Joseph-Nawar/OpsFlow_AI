from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from opsflow.evaluation.artifacts import validate_result_json
from opsflow.evaluation.comparison import ComparisonResult, compare_runs
from opsflow.evaluation.corpus import load_manifest
from opsflow.evaluation.models import (
    CaseResultStatus,
    CostMetrics,
    EvaluationMode,
    EvaluationRunResult,
    ExtractionQuality,
    ExtractionQualityStatus,
    PricingStatus,
    ProviderSummary,
    ProviderUsageMetrics,
    RateMetric,
    ReleaseGateSummary,
    TimingMetric,
    ValidationRoute,
)
from opsflow.evaluation.scoring import build_routing_metrics, evaluate_release_gates

REFERENCE = (
    Path(__file__).resolve().parents[2]
    / "docs/evaluation/reference/phase-11-provider-free-baseline.json"
)


def baseline_result():
    return validate_result_json(REFERENCE)


def _with_run(result, **updates):
    return result.model_copy(update={"run": result.run.model_copy(update=updates)})


def _as_live(result, *, model: str = "gemini-3.8-flash", snapshot: str = "gemini-2026-10"):
    run = result.run.model_copy(update={"mode": EvaluationMode.LIVE_GEMINI, "gemini_model": model})
    first_case = result.cases[0]
    cases = (
        first_case.model_copy(
            update={
                "provider": ProviderSummary(
                    name="gemini",
                    calls=1,
                    input_tokens=11,
                    output_tokens=7,
                    total_tokens=18,
                ),
                "durations_ms": first_case.durations_ms.model_copy(
                    update={"live_gemini_call_ms": Decimal("4.5")}
                ),
            }
        ),
        *result.cases[1:],
    )
    metrics = result.metrics.model_copy(
        update={
            "extraction_quality": ExtractionQuality(
                status=ExtractionQualityStatus.AVAILABLE,
                complete_exact_match=RateMetric(numerator=1, denominator=1, value=Decimal("1")),
                field_tp=3,
                field_fp=0,
                field_fn=0,
                field_micro_precision=RateMetric(numerator=3, denominator=3, value=Decimal("1")),
                field_micro_recall=RateMetric(numerator=3, denominator=3, value=Decimal("1")),
                field_micro_f1=RateMetric(numerator=3, denominator=3, value=Decimal("1")),
                reached_live_gemini_case_count=1,
                reached_live_gemini_case_ids=(first_case.case_id,),
                reason="Mocked Gemini evidence for comparison contract tests.",
            ),
            "latency": result.metrics.latency.model_copy(
                update={
                    "provider_free_intake_ms": TimingMetric(),
                    "live_gemini_call_ms": TimingMetric(
                        sample_count=1,
                        minimum_ms=Decimal("4.5"),
                        maximum_ms=Decimal("4.5"),
                        sum_ms=Decimal("4.5"),
                        p50_ms=Decimal("4.5"),
                        p95_ms=Decimal("4.5"),
                    ),
                }
            ),
            "provider_usage": ProviderUsageMetrics(
                status="AVAILABLE",
                gemini_call_count=1,
                calls_per_initial_order=Decimal(1) / Decimal(36),
                input_tokens_sum=11,
                available_input_token_count=1,
                average_input_tokens=Decimal("11"),
                output_tokens_sum=7,
                available_output_token_count=1,
                average_output_tokens=Decimal("7"),
                total_tokens_sum=18,
                available_total_token_count=1,
                average_total_tokens=Decimal("18"),
            ),
            "cost": CostMetrics(
                status="AVAILABLE",
                estimated_model_cost_per_initial_order=Decimal("0.01"),
                initial_order_count=36,
                gemini_called_order_count=1,
                zero_call_order_count=35,
                complete_usage_order_count=1,
            ),
        }
    )
    return EvaluationRunResult.model_validate(
        {
            **result.model_dump(mode="python"),
            "run": run,
            "cases": cases,
            "metrics": metrics,
            "pricing": PricingStatus(
                pricing_snapshot_id=snapshot,
                model=model,
                status="AVAILABLE",
            ),
        }
    )


def test_matching_results_are_comparable_and_report_both_git_shas() -> None:
    baseline = baseline_result()
    candidate = _with_run(baseline, git_sha="b" * 40)

    comparison = compare_runs(baseline, candidate)

    assert isinstance(comparison, ComparisonResult)
    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True
    assert comparison.invariant_mismatches == ()
    assert comparison.baseline_git_sha == baseline.run.git_sha
    assert comparison.candidate_git_sha == "b" * 40


def test_run_id_timestamps_and_git_sha_may_differ() -> None:
    baseline = baseline_result()
    candidate = _with_run(
        baseline,
        run_id="a1491a42-3926-4d4b-aef9-5b88097fdf05",
        started_at_utc=datetime(2026, 10, 11, tzinfo=UTC),
        finished_at_utc=datetime(2026, 10, 11, 0, 1, tzinfo=UTC),
        git_sha="c" * 40,
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True
    assert comparison.invariant_mismatches == ()
    assert comparison.baseline_git_sha != comparison.candidate_git_sha


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("corpus_version", "4.0.0"),
        ("schema_version", "opsflow-evaluation-result/v2"),
        ("evaluation_version", "phase11-v2"),
        ("mode", EvaluationMode.LIVE_GEMINI),
        ("command", "make evaluate --different-contract"),
    ],
)
def test_correctness_contract_mismatches_prevent_comparison(field: str, value: object) -> None:
    baseline = baseline_result()
    candidate = (
        baseline.model_copy(update={field: value})
        if field in {"schema_version", "evaluation_version"}
        else _with_run(baseline, **{field: value})
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is False
    assert comparison.latency_comparable is False
    assert comparison.invariant_mismatches


def test_case_identity_and_corpus_composition_must_match() -> None:
    baseline = baseline_result()
    candidate = baseline.model_copy(update={"cases": baseline.cases[:-1]})

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is False
    assert any(
        "case" in mismatch or "corpus" in mismatch for mismatch in comparison.invariant_mismatches
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"python_version": "3.11.9"},
        {"dependency_lock_identity": "other.lock"},
        {"platform": "Linux"},
        {"cpu_architecture": "x86_64"},
        {"database_version": "PostgreSQL 15"},
    ],
)
def test_latency_environment_mismatch_preserves_correctness_comparison(
    updates: dict[str, str],
) -> None:
    baseline = baseline_result()
    candidate = _with_run(baseline, **updates)

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False
    assert comparison.latency_limitation is not None
    assert any(item.startswith("latency:") for item in comparison.invariant_mismatches)


def test_python_patch_and_database_minor_version_differences_are_compatible() -> None:
    baseline = baseline_result()
    candidate = _with_run(baseline, python_version="3.12.99", database_version="PostgreSQL 16.8")

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True


def test_timing_method_or_sample_applicability_mismatch_limits_latency() -> None:
    baseline = baseline_result()
    latency = baseline.metrics.latency
    changed_metric = latency.provider_free_intake_ms.model_copy(
        update={"percentile_method": "linear_interpolation"}
    )
    candidate = baseline.model_copy(
        update={
            "metrics": baseline.metrics.model_copy(
                update={
                    "latency": latency.model_copy(
                        update={"provider_free_intake_ms": changed_metric}
                    )
                }
            )
        }
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False


def test_timing_sample_availability_mismatch_limits_latency() -> None:
    baseline = baseline_result()
    latency = baseline.metrics.latency
    candidate = baseline.model_copy(
        update={
            "metrics": baseline.metrics.model_copy(
                update={"latency": latency.model_copy(update={"parse_ms": TimingMetric()})}
            )
        }
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False


def test_database_engine_and_isolation_are_required_for_latency_comparison() -> None:
    baseline = baseline_result()
    database = baseline.run.database.model_copy(update={"engine": "sqlite"})
    candidate = baseline.model_copy(
        update={"run": baseline.run.model_copy(update={"database": database})}
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False


def test_missing_latency_metadata_is_not_assumed_compatible() -> None:
    baseline = baseline_result()
    candidate = _with_run(
        baseline,
        python_version=None,
        dependency_lock_identity=None,
        platform=None,
        database_version=None,
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False
    with pytest.raises(ValueError, match="latency"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


@pytest.mark.parametrize("field", ["gemini_model", "pricing_snapshot_id"])
def test_live_model_or_cost_pricing_mismatch_prevents_live_comparison(field: str) -> None:
    baseline = _as_live(baseline_result())
    candidate = _as_live(
        baseline_result(),
        model="gemini-3.8-pro" if field == "gemini_model" else "gemini-3.8-flash",
        snapshot="other-snapshot" if field == "pricing_snapshot_id" else "gemini-2026-10",
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is False
    assert comparison.latency_comparable is False


def test_live_attempt_timing_population_must_match_attributed_provider_calls() -> None:
    baseline = _as_live(baseline_result())
    live_timing = baseline.metrics.latency.live_gemini_call_ms.model_copy(
        update={"sample_count": 2, "sum_ms": Decimal("9")}
    )
    candidate = baseline.model_copy(
        update={
            "metrics": baseline.metrics.model_copy(
                update={
                    "latency": baseline.metrics.latency.model_copy(
                        update={"live_gemini_call_ms": live_timing}
                    )
                }
            )
        }
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.candidate_evidence_valid is False
    assert comparison.latency_comparable is False


def test_provider_free_cost_not_applicable_does_not_require_pricing_metadata() -> None:
    baseline = baseline_result()
    candidate = _with_run(baseline, git_sha="d" * 40)

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True


def test_failed_case_or_release_gate_cannot_be_used_as_optimization_baseline() -> None:
    baseline = baseline_result()
    failed_case = baseline.cases[0].model_copy(update={"status": CaseResultStatus.FAIL})
    candidate = baseline.model_copy(update={"cases": (failed_case, *baseline.cases[1:])})

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is False
    assert comparison.latency_comparable is False
    with pytest.raises(ValueError, match="valid baseline and candidate evidence"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


def test_missing_or_failed_release_gate_is_not_a_safe_comparison() -> None:
    baseline = baseline_result()
    failed_gates = ReleaseGateSummary(
        all_passed=False,
        results=baseline.release_gates.results[:-1]
        + (baseline.release_gates.results[-1].model_copy(update={"status": "FAIL"}),),
    )
    candidate = baseline.model_copy(update={"release_gates": failed_gates})

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is False
    assert any("gate" in mismatch for mismatch in comparison.invariant_mismatches)


def test_gate_status_cannot_hide_observed_authority_violations() -> None:
    baseline = baseline_result()
    gates = tuple(
        gate.model_copy(update={"numerator": 1})
        if gate.gate_id == "direct_llm_side_effects_zero"
        else gate
        for gate in baseline.release_gates.results
    )
    candidate = baseline.model_copy(
        update={"release_gates": ReleaseGateSummary(all_passed=True, results=gates)}
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is False


def test_optimization_claim_is_rejected_when_latency_is_incomparable() -> None:
    baseline = baseline_result()
    candidate = _with_run(baseline, platform="Linux")
    comparison = compare_runs(baseline, candidate)

    with pytest.raises(ValueError, match="latency"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


def _corpus():
    return load_manifest(Path(__file__).resolve().parents[2] / "evals/corpus/v1")


def _with_cases_and_recomputed_scores(result, cases):
    corpus = _corpus()
    gates = evaluate_release_gates(corpus, cases)
    metrics = result.metrics.model_copy(
        update={"routing": build_routing_metrics(corpus, cases, gates)}
    )
    return result.model_copy(
        update={
            "cases": cases,
            "release_gates": gates,
            "metrics": metrics,
        }
    )


def test_pass_case_with_false_validation_score_is_invalid_evidence() -> None:
    baseline = baseline_result()
    first = baseline.cases[0]
    contradictory = first.model_copy(
        update={"scores": first.scores.model_copy(update={"validation_match": False})}
    )
    candidate = baseline.model_copy(update={"cases": (contradictory, *baseline.cases[1:])})

    comparison = compare_runs(baseline, candidate)

    assert comparison.candidate_evidence_valid is False
    assert comparison.correctness_comparable is False
    assert comparison.candidate_correctness_passed is None
    with pytest.raises(ValueError, match="evidence"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


def test_failed_validation_score_without_observation_is_not_a_real_regression() -> None:
    baseline = baseline_result()
    first = baseline.cases[0]
    fabricated_failure = first.model_copy(
        update={
            "status": CaseResultStatus.FAIL,
            "scores": first.scores.model_copy(update={"validation_match": False}),
        }
    )
    candidate = baseline.model_copy(update={"cases": (fabricated_failure, *baseline.cases[1:])})

    comparison = compare_runs(baseline, candidate)

    assert comparison.candidate_evidence_valid is False
    assert comparison.correctness_comparable is False


def test_provider_free_comparison_rejects_real_gemini_call_evidence() -> None:
    baseline = baseline_result()
    first = baseline.cases[0]
    called_gemini = first.model_copy(update={"provider": ProviderSummary(name="gemini", calls=1)})
    candidate = baseline.model_copy(update={"cases": (called_gemini, *baseline.cases[1:])})

    comparison = compare_runs(baseline, candidate)

    assert comparison.candidate_evidence_valid is False
    assert comparison.correctness_comparable is False


@pytest.mark.parametrize(
    ("status", "score_updates"),
    [
        (CaseResultStatus.PASS, {"replay_match": False}),
        (CaseResultStatus.FAIL, {"validation_match": True}),
        (CaseResultStatus.FAIL, {}),
    ],
)
def test_case_status_and_applicable_scores_must_agree(status, score_updates) -> None:
    baseline = baseline_result()
    case_index = next(
        index for index, case in enumerate(baseline.cases) if case.actual.replay is not None
    )
    cases = list(baseline.cases)
    case = cases[case_index]
    scores = case.scores.model_copy(update=score_updates)
    cases[case_index] = case.model_copy(update={"status": status, "scores": scores})
    candidate = _with_cases_and_recomputed_scores(baseline, tuple(cases))

    comparison = compare_runs(baseline, candidate)

    assert comparison.candidate_evidence_valid is False
    assert comparison.correctness_comparable is False


def test_same_wrong_gate_populations_are_rejected_against_canonical_corpus() -> None:
    baseline = baseline_result()
    invalid_gates = ReleaseGateSummary(
        all_passed=True,
        results=tuple(
            gate.model_copy(
                update={
                    "numerator": numerator,
                    "denominator": denominator,
                    "status": "PASS",
                    "failing_case_ids": (),
                }
            )
            for gate, numerator, denominator in zip(
                baseline.release_gates.results,
                (0, 1, 1, 1, 0),
                (1, 1, 1, 1, 36),
                strict=True,
            )
        ),
    )
    candidate = baseline.model_copy(update={"release_gates": invalid_gates})

    comparison = compare_runs(candidate, candidate)

    assert comparison.baseline_evidence_valid is False
    assert comparison.candidate_evidence_valid is False
    assert comparison.correctness_comparable is False


def test_gate_numerator_and_status_must_match_case_observations() -> None:
    baseline = baseline_result()
    failed_gate = baseline.release_gates.results[1].model_copy(
        update={"numerator": 6, "status": "FAIL", "failing_case_ids": ("fabricated",)}
    )
    gates = baseline.release_gates.model_copy(
        update={
            "all_passed": False,
            "results": (
                baseline.release_gates.results[0],
                failed_gate,
                *baseline.release_gates.results[2:],
            ),
        }
    )
    candidate = baseline.model_copy(update={"release_gates": gates})

    comparison = compare_runs(baseline, candidate)

    assert comparison.candidate_evidence_valid is False
    assert comparison.candidate_correctness_passed is None


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_required_case_identity_evidence_must_be_complete_and_unique(mutation: str) -> None:
    baseline = baseline_result()
    if mutation == "missing":
        cases = baseline.cases[:-1]
    else:
        cases = (*baseline.cases[:-1], baseline.cases[0])
    candidate = baseline.model_copy(update={"cases": cases})

    comparison = compare_runs(baseline, candidate)

    assert comparison.candidate_evidence_valid is False
    assert comparison.correctness_comparable is False


def test_sound_failed_candidate_remains_comparable_but_not_optimization_eligible() -> None:
    baseline = baseline_result()
    failing_case = next(
        case for case in baseline.cases if case.case_id == "deterministic-email-001"
    )
    failed = failing_case.model_copy(
        update={
            "status": CaseResultStatus.FAIL,
            "actual": failing_case.actual.model_copy(
                update={"route": ValidationRoute.READY_FOR_APPROVAL}
            ),
            "scores": failing_case.scores.model_copy(update={"validation_match": False}),
        }
    )
    cases = tuple(failed if case.case_id == failed.case_id else case for case in baseline.cases)
    candidate = _with_cases_and_recomputed_scores(baseline, cases)
    faster_intake = candidate.metrics.latency.provider_free_intake_ms.model_copy(
        update={"p95_ms": Decimal("100")}
    )
    candidate = candidate.model_copy(
        update={
            "metrics": candidate.metrics.model_copy(
                update={
                    "latency": candidate.metrics.latency.model_copy(
                        update={"provider_free_intake_ms": faster_intake}
                    )
                }
            )
        }
    )

    comparison = compare_runs(baseline, candidate)

    assert candidate.release_gates.results[1].numerator == 6
    assert candidate.release_gates.results[1].denominator == 7
    assert comparison.candidate_evidence_valid is True
    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True
    assert comparison.baseline_correctness_passed is True
    assert comparison.candidate_correctness_passed is False
    assert comparison.optimization_eligible is False
    with pytest.raises(ValueError, match="candidate correctness"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


def test_identical_comparable_metrics_do_not_establish_an_optimization_claim() -> None:
    baseline = baseline_result()
    candidate = _with_run(baseline, git_sha="f" * 40)

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True
    assert comparison.optimization_eligible is False
    with pytest.raises(ValueError, match="observed latency improvement"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


def test_matching_passing_runs_need_an_observed_metric_improvement_for_claim() -> None:
    baseline = baseline_result()
    metric = baseline.metrics.latency.provider_free_intake_ms
    improved = metric.model_copy(update={"p95_ms": Decimal("104.5")})
    candidate_latency = baseline.metrics.latency.model_copy(
        update={"provider_free_intake_ms": improved}
    )
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={"latency": candidate_latency})}
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True
    assert comparison.baseline_correctness_passed is True
    assert comparison.candidate_correctness_passed is True
    assert comparison.optimization_eligible is True
    comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")
    with pytest.raises(ValueError, match="no observed latency improvement"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p50_ms")


@pytest.mark.parametrize(
    "updates",
    [
        {"p95_ms": Decimal("200")},
        {"p50_ms": Decimal("105"), "p95_ms": Decimal("104")},
        {"minimum_ms": Decimal("100"), "maximum_ms": Decimal("50")},
        {"sum_ms": Decimal("1")},
    ],
)
def test_impossible_timing_summary_is_not_latency_evidence(updates) -> None:
    baseline = baseline_result()
    metric = baseline.metrics.latency.provider_free_intake_ms.model_copy(update=updates)
    candidate = baseline.model_copy(
        update={
            "metrics": baseline.metrics.model_copy(
                update={
                    "latency": baseline.metrics.latency.model_copy(
                        update={"provider_free_intake_ms": metric}
                    )
                }
            )
        }
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False
    assert comparison.optimization_eligible is False
    with pytest.raises(ValueError, match="evidence"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


def test_single_sample_timing_summary_requires_equal_extrema_and_aggregates() -> None:
    baseline = baseline_result()
    metric = TimingMetric(
        sample_count=1,
        minimum_ms=Decimal("1"),
        maximum_ms=Decimal("1"),
        sum_ms=Decimal("1"),
        p50_ms=Decimal("1"),
        p95_ms=Decimal("1"),
    )
    impossible = metric.model_copy(update={"p95_ms": Decimal("2")})
    candidate = baseline.model_copy(
        update={
            "metrics": baseline.metrics.model_copy(
                update={
                    "latency": baseline.metrics.latency.model_copy(
                        update={"provider_free_intake_ms": impossible}
                    )
                }
            )
        }
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.latency_comparable is False


def test_provider_free_normal_intake_requires_complete_contract_population() -> None:
    baseline = baseline_result()
    timing = baseline.metrics.latency.provider_free_intake_ms
    incomplete = timing.model_copy(
        update={
            "sample_count": 1,
            "minimum_ms": Decimal("1"),
            "maximum_ms": Decimal("1"),
            "sum_ms": Decimal("1"),
            "p50_ms": Decimal("1"),
            "p95_ms": Decimal("1"),
        }
    )
    candidate = baseline.model_copy(
        update={
            "metrics": baseline.metrics.model_copy(
                update={
                    "latency": baseline.metrics.latency.model_copy(
                        update={"provider_free_intake_ms": incomplete}
                    )
                }
            )
        }
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False
    assert comparison.optimization_eligible is False


def test_valid_unavailable_live_stage_remains_comparable_for_provider_free_runs() -> None:
    baseline = baseline_result()

    comparison = compare_runs(baseline, _with_run(baseline, git_sha="e" * 40))

    assert comparison.candidate_evidence_valid is True
    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is True
    assert comparison.baseline_correctness_passed is True
    assert comparison.candidate_correctness_passed is True
    assert comparison.optimization_eligible is False
    with pytest.raises(ValueError, match="observed latency improvement"):
        comparison.require_optimization_claim(stage="provider_free_intake_ms", percentile="p95_ms")


def test_sound_timing_with_a_different_method_preserves_correctness_comparison() -> None:
    baseline = baseline_result()
    baseline_latency = baseline.metrics.latency
    candidate_latency = baseline_latency.model_copy(
        update={
            "provider_free_intake_ms": baseline_latency.provider_free_intake_ms.model_copy(
                update={"percentile_method": "linear_interpolation"}
            )
        }
    )
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={"latency": candidate_latency})}
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False


def test_zero_sample_timing_with_reported_values_is_invalid() -> None:
    baseline = baseline_result()
    reported_without_samples = baseline.metrics.latency.provider_free_intake_ms.model_copy(
        update={
            "sample_count": 0,
            "minimum_ms": None,
            "maximum_ms": None,
            "sum_ms": None,
            "p50_ms": Decimal("1"),
            "p95_ms": None,
        }
    )
    latency = baseline.metrics.latency.model_copy(
        update={"provider_free_intake_ms": reported_without_samples}
    )
    candidate = baseline.model_copy(
        update={"metrics": baseline.metrics.model_copy(update={"latency": latency})}
    )

    comparison = compare_runs(baseline, candidate)

    assert comparison.correctness_comparable is True
    assert comparison.latency_comparable is False
    assert comparison.candidate_evidence_valid is False
