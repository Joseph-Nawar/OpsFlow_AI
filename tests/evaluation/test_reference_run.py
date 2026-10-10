from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from opsflow.evaluation.artifacts import render_markdown_from_json, validate_result_json
from opsflow.evaluation.corpus import load_manifest, resolve_manifest_source
from opsflow.evaluation.models import (
    CaseActual,
    CaseResult,
    CaseResultStatus,
    CorpusComposition,
    CostMetrics,
    DatabaseMetadata,
    DurationSummary,
    EvaluationMode,
    EvaluationRunResult,
    ExtractionQuality,
    ExtractionQualityStatus,
    LatencyMetrics,
    MetricsBundle,
    PricingStatus,
    ProviderSummary,
    ProviderUsageMetrics,
    RateMetric,
    ReleaseGateSummary,
    RunMetadata,
    TimingMetric,
)

REFERENCE_DIRECTORY = Path("docs/evaluation/reference")
BASELINE_JSON = REFERENCE_DIRECTORY / "phase-11-provider-free-baseline.json"
BASELINE_MARKDOWN = REFERENCE_DIRECTORY / "phase-11-provider-free-baseline.md"
LIVE_UNAVAILABLE = REFERENCE_DIRECTORY / "phase-11-live-gemini-unavailable.md"
MEASURED_RUN_SHA = "7b67e6e32a2c7f7c44894dcf38eb68968ce1195b"
LIVE_MODEL = "gemini-3.8-flash"

EXPECTED_GATES = {
    "invalid_orders_executed_zero": (0, 13, "PASS"),
    "deterministic_violation_routing_100": (7, 7, "PASS"),
    "duplicate_blocking_100": (4, 4, "PASS"),
    "malformed_security_safe_100": (4, 4, "PASS"),
    "direct_llm_side_effects_zero": (0, 36, "PASS"),
}


def _assert_timing_summary_is_valid(metric) -> None:
    assert metric.percentile_method == "nearest_rank_no_interpolation"
    if metric.sample_count == 0:
        assert metric.minimum_ms is None
        assert metric.maximum_ms is None
        assert metric.sum_ms is None
        assert metric.p50_ms is None
        assert metric.p95_ms is None
        return
    assert metric.minimum_ms is not None
    assert metric.maximum_ms is not None
    assert metric.sum_ms is not None
    assert metric.p50_ms is not None
    assert metric.p95_ms is not None
    assert metric.minimum_ms <= metric.p50_ms <= metric.maximum_ms
    assert metric.minimum_ms <= metric.p95_ms <= metric.maximum_ms
    assert metric.sum_ms >= metric.maximum_ms


def _mock_live_result(pricing_model: str | None) -> EvaluationRunResult:
    case_id = "live-case-001"
    return EvaluationRunResult(
        run=RunMetadata(
            run_id="mock-live-run",
            mode=EvaluationMode.LIVE_GEMINI,
            started_at_utc=datetime(2026, 10, 10, tzinfo=UTC),
            finished_at_utc=datetime(2026, 10, 10, 0, 1, tzinfo=UTC),
            git_sha="a" * 40,
            corpus_version="3.0.0",
            command="make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1",
            dependency_lock_identity="uv.lock",
            database_version="PostgreSQL 16",
            gemini_model=LIVE_MODEL,
            python_version="3.12.13",
            platform="Darwin",
            cpu_architecture="arm64",
            database=DatabaseMetadata(engine="PostgreSQL 16", isolated=True),
        ),
        corpus=CorpusComposition(
            case_count=1,
            primary_category_counts={},
            format_counts={},
            tag_counts={},
        ),
        cases=(
            CaseResult(
                case_id=case_id,
                status=CaseResultStatus.PASS,
                actual=CaseActual(parse=CaseResultStatus.PASS),
                durations_ms=DurationSummary(live_gemini_call_ms=Decimal("4.5")),
                provider=ProviderSummary(
                    name="gemini",
                    calls=1,
                    input_tokens=11,
                    output_tokens=7,
                    total_tokens=18,
                ),
            ),
        ),
        metrics=MetricsBundle(
            extraction_quality=ExtractionQuality(
                status=ExtractionQualityStatus.AVAILABLE,
                complete_exact_match=RateMetric(numerator=1, denominator=1, value=Decimal("1")),
                field_tp=3,
                field_fp=0,
                field_fn=0,
                field_micro_precision=RateMetric(numerator=3, denominator=3, value=Decimal("1")),
                field_micro_recall=RateMetric(numerator=3, denominator=3, value=Decimal("1")),
                field_micro_f1=RateMetric(numerator=3, denominator=3, value=Decimal("1")),
                reached_live_gemini_case_count=1,
                reached_live_gemini_case_ids=(case_id,),
                reason="One mocked Gemini extraction case contributed to quality metrics.",
            ),
            latency=LatencyMetrics(
                live_gemini_call_ms=TimingMetric(
                    sample_count=1,
                    minimum_ms=Decimal("4.5"),
                    maximum_ms=Decimal("4.5"),
                    sum_ms=Decimal("4.5"),
                    p50_ms=Decimal("4.5"),
                    p95_ms=Decimal("4.5"),
                )
            ),
            provider_usage=ProviderUsageMetrics(
                status="AVAILABLE",
                gemini_call_count=1,
                calls_per_initial_order=Decimal("1"),
                input_tokens_sum=11,
                available_input_token_count=1,
                missing_input_token_count=0,
                average_input_tokens=Decimal("11"),
                output_tokens_sum=7,
                available_output_token_count=1,
                missing_output_token_count=0,
                average_output_tokens=Decimal("7"),
                total_tokens_sum=18,
                available_total_token_count=1,
                missing_total_token_count=0,
                average_total_tokens=Decimal("18"),
            ),
            cost=CostMetrics(
                status="ERROR",
                estimated_model_cost_per_initial_order=None,
                initial_order_count=1,
                gemini_called_order_count=1,
                incomplete_usage_order_count=1,
                missing_pricing_snapshot_count=1,
            ),
        ),
        pricing=PricingStatus(
            status="ERROR",
            model=pricing_model,
            reason=(
                "No matching pricing snapshot was available; estimated model cost is unavailable."
            ),
        ),
        release_gates=ReleaseGateSummary(),
        limitations=("Estimated model cost is unavailable.",),
    )


def test_provider_free_reference_matches_the_measured_36_case_run() -> None:
    raw_json = BASELINE_JSON.read_text(encoding="utf-8")
    result = validate_result_json(raw_json)
    manifest = load_manifest(Path("evals/corpus/v1"))

    assert result.run.mode is EvaluationMode.PROVIDER_FREE
    assert result.run.git_sha == MEASURED_RUN_SHA
    assert result.run.corpus_version == manifest.corpus_version == "3.0.0"
    assert result.schema_version == "opsflow-evaluation-result/v1"
    assert result.evaluation_version == "phase11-v1"
    assert result.corpus.case_count == len(result.cases) == 36
    assert {case.case_id for case in result.cases} == {case.case_id for case in manifest.cases}
    assert all(case.status is CaseResultStatus.PASS for case in result.cases)

    quality = result.metrics.extraction_quality
    assert quality.status is ExtractionQualityStatus.NOT_APPLICABLE
    assert quality.reached_live_gemini_case_count == 0
    assert quality.complete_exact_match is None
    assert result.run.gemini_model is None
    assert result.run.python_version
    assert result.run.platform
    assert result.run.cpu_architecture
    assert result.run.database_version.startswith("PostgreSQL ")
    assert result.run.database.isolated is True
    assert result.run.command == "make evaluate"
    assert result.run.dependency_lock_identity == "uv.lock"
    assert result.metrics.provider_usage.gemini_call_count == 0
    assert result.metrics.provider_usage.status == "NOT_APPLICABLE"
    assert result.metrics.cost.status == "NOT_APPLICABLE"
    assert result.metrics.cost.estimated_model_cost_per_initial_order is None
    assert result.pricing.status == "NOT_APPLICABLE"
    assert result.limitations

    gates = {
        gate.gate_id: (gate.numerator, gate.denominator, gate.status)
        for gate in result.release_gates.results
    }
    assert result.release_gates.all_passed is True
    assert gates == EXPECTED_GATES
    routing = result.metrics.routing
    assert (routing.full_routing_accuracy.numerator, routing.full_routing_accuracy.denominator) == (
        14,
        14,
    )
    assert (routing.retry_recovery.numerator, routing.retry_recovery.denominator) == (3, 3)
    assert (routing.execution_safety.numerator, routing.execution_safety.denominator) == (14, 14)
    assert routing.logical_duplication_count == 0

    replay_results = [case for case in result.cases if case.actual.replay is not None]
    assert len(replay_results) == 4
    for case in replay_results:
        replay = case.actual.replay
        assert replay is not None
        assert replay.creation_disposition.value == "REPLAYED_EXISTING"
        assert replay.intake_execution.value == "STANDING_DOWN"
        assert replay.seed_order_id == replay.replay_order_id == case.actual.order_id
        assert replay.notification_intents_before == replay.notification_intents_after
        assert replay.order_sync_intents_before == replay.order_sync_intents_after
        assert replay.provider_calls_before == replay.provider_calls_after

    latency = result.metrics.latency
    for metric in (
        latency.parse_ms,
        latency.deterministic_validation_ms,
        latency.provider_free_intake_ms,
        latency.provider_free_replay_intake_ms,
        latency.provider_free_recovery_intake_ms,
        latency.live_gemini_call_ms,
    ):
        _assert_timing_summary_is_valid(metric)
    assert latency.parse_ms.sample_count > 0
    assert latency.deterministic_validation_ms.sample_count > 0
    assert latency.provider_free_intake_ms.sample_count > 0
    assert latency.provider_free_replay_intake_ms.sample_count > 0
    assert latency.provider_free_recovery_intake_ms.sample_count > 0
    assert latency.live_gemini_call_ms.sample_count == 0

    raw_bytes = raw_json.encode("utf-8")
    for case in manifest.cases:
        source = resolve_manifest_source(Path("evals/corpus/v1"), case.source.path)
        assert source.read_bytes() not in raw_bytes

    expected_markdown = render_markdown_from_json(raw_json)
    assert BASELINE_MARKDOWN.read_text(encoding="utf-8") == expected_markdown
    assert result.run.run_id in expected_markdown
    assert "0/13" in expected_markdown
    assert "7/7" in expected_markdown
    assert "4/4" in expected_markdown


def test_live_gemini_unavailability_is_explicit_and_has_no_fake_reference_pair() -> None:
    text = LIVE_UNAVAILABLE.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "has not been measured" in text
    assert "extraction accuracy" in text
    assert "input and output tokens" in normalized
    assert "provider latency" in text
    assert "estimated model cost" in text
    assert not (REFERENCE_DIRECTORY / "phase-11-live-gemini-reference.json").exists()
    assert not (REFERENCE_DIRECTORY / "phase-11-live-gemini-reference.md").exists()


@pytest.mark.parametrize("pricing_model", [None, "gemini-other-model"])
def test_mock_live_evidence_keeps_provider_metrics_and_marks_cost_unavailable(
    pricing_model: str | None,
) -> None:
    result = validate_result_json(_mock_live_result(pricing_model).model_dump(mode="json"))
    reached_ids = tuple(case.case_id for case in result.cases if case.provider.name == "gemini")

    assert result.run.mode is EvaluationMode.LIVE_GEMINI
    assert result.run.gemini_model == LIVE_MODEL
    assert result.metrics.extraction_quality.reached_live_gemini_case_count == len(reached_ids) == 1
    assert result.metrics.extraction_quality.reached_live_gemini_case_ids == reached_ids
    assert result.metrics.extraction_quality.complete_exact_match == RateMetric(
        numerator=1, denominator=1, value=Decimal("1")
    )
    assert result.metrics.extraction_quality.field_tp == 3
    assert result.metrics.extraction_quality.field_fp == 0
    assert result.metrics.extraction_quality.field_fn == 0
    assert result.metrics.latency.live_gemini_call_ms.p50_ms == Decimal("4.5")
    assert result.metrics.provider_usage.input_tokens_sum == 11
    assert result.metrics.provider_usage.output_tokens_sum == 7
    assert result.metrics.provider_usage.total_tokens_sum == 18
    assert result.metrics.provider_usage.missing_input_token_count == 0
    assert result.metrics.provider_usage.missing_output_token_count == 0
    assert result.metrics.provider_usage.missing_total_token_count == 0
    assert result.metrics.cost.status == "ERROR"
    assert result.metrics.cost.estimated_model_cost_per_initial_order is None
    assert result.pricing.status == "ERROR"
    assert "cost is unavailable" in result.pricing.reason
