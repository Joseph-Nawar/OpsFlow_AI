from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from opsflow.evaluation.models import (
    CaseActual,
    CaseResult,
    CaseResultStatus,
    CaseScores,
    ContractEvidence,
    CorpusComposition,
    CostMetrics,
    DatabaseMetadata,
    DurationSummary,
    EvaluationMode,
    EvaluationRunResult,
    ExtractionQuality,
    ExtractionQualityStatus,
    MetricsBundle,
    PricingStatus,
    ProviderSummary,
    RateMetric,
    ReleaseGateSummary,
    RunMetadata,
)


def valid_quality() -> ExtractionQuality:
    return ExtractionQuality(
        status=ExtractionQualityStatus.NOT_APPLICABLE,
        complete_exact_match=None,
        field_tp=None,
        field_fp=None,
        field_fn=None,
        field_micro_precision=None,
        field_micro_recall=None,
        field_micro_f1=None,
        per_field=None,
        reached_live_gemini_case_count=0,
        reason="No real model was evaluated in provider-free mode.",
    )


def valid_case(*, reached: bool = False, provider_name: str | None = None) -> CaseResult:
    return CaseResult(
        case_id="normal-001",
        status=CaseResultStatus.PASS,
        actual=CaseActual(
            parse=CaseResultStatus.PASS,
            extraction_contract=CaseResultStatus.PASS,
        ),
        scores=CaseScores(),
        provider=ProviderSummary(
            name=provider_name,
            calls=1 if reached else 0,
        ),
    )


def valid_run(
    *,
    mode: EvaluationMode = EvaluationMode.PROVIDER_FREE,
    cases: tuple[CaseResult, ...] | None = None,
    metrics: MetricsBundle | None = None,
) -> EvaluationRunResult:
    return EvaluationRunResult(
        run=RunMetadata(
            run_id="run-001",
            mode=mode,
            started_at_utc=datetime(2026, 10, 8, tzinfo=UTC),
            finished_at_utc=datetime(2026, 10, 8, 0, 1, tzinfo=UTC),
            git_sha="a" * 40,
            corpus_version="1.0.0",
            command="make evaluate",
            dependency_lock_identity="uv.lock",
            database_version="PostgreSQL 16",
            database=DatabaseMetadata(engine="postgresql", isolated=True),
        ),
        corpus=CorpusComposition(
            case_count=1,
            primary_category_counts={},
            format_counts={},
            tag_counts={},
        ),
        cases=cases or (valid_case(),),
        metrics=metrics or MetricsBundle(extraction_quality=valid_quality()),
        pricing=PricingStatus(status="NOT_APPLICABLE"),
        release_gates=ReleaseGateSummary(),
    )


def test_result_has_exact_stable_top_level_keys() -> None:
    assert set(valid_run().model_dump(mode="json")) == {
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


def test_case_has_exact_nested_stable_keys() -> None:
    case = valid_run().model_dump(mode="json")["cases"][0]
    assert set(case) == {
        "case_id",
        "status",
        "actual",
        "scores",
        "durations_ms",
        "provider",
        "side_effects",
    }
    assert case["actual"]["extraction_contract"] == "PASS"
    assert case["provider"]["calls"] == 0


def test_provider_free_result_is_explicitly_not_applicable_for_model_quality() -> None:
    result = valid_run(
        metrics=MetricsBundle(
            extraction_quality=valid_quality(),
            extraction_contract=ContractEvidence(
                parser_succeeded=True,
                evidence_grounded=True,
                scripted_provider_call_count=1,
            ),
        )
    )
    payload = result.model_dump(mode="json")

    assert payload["run"]["mode"] == "provider_free"
    assert payload["metrics"]["extraction_contract"]["parser_succeeded"] is True
    assert "accuracy" not in payload["metrics"]["extraction_contract"]
    assert payload["metrics"]["extraction_quality"]["status"] == "NOT_APPLICABLE"
    assert payload["metrics"]["extraction_quality"]["reason"]
    assert payload["metrics"]["extraction_quality"]["field_micro_precision"] is None


def test_provider_free_result_cannot_publish_a_scripted_extraction_score() -> None:
    with pytest.raises(ValidationError, match="NOT_APPLICABLE"):
        valid_run(
            metrics=MetricsBundle(
                extraction_quality=ExtractionQuality(
                    status=ExtractionQualityStatus.AVAILABLE,
                    complete_exact_match=RateMetric(numerator=1, denominator=1, value=Decimal("1")),
                    reason="scripted provider matched",
                )
            )
        )


def test_not_applicable_quality_cannot_contain_a_rate() -> None:
    with pytest.raises(ValidationError, match="NOT_APPLICABLE"):
        ExtractionQuality(
            status=ExtractionQualityStatus.NOT_APPLICABLE,
            complete_exact_match=RateMetric(numerator=1, denominator=1, value=Decimal("1")),
            reason="No real model was evaluated.",
        )


def test_error_is_valid_and_skipped_is_rejected() -> None:
    error = CaseResult(
        case_id="broken-001",
        status=CaseResultStatus.ERROR,
        actual=CaseActual(
            parse=CaseResultStatus.ERROR,
            failure_code="PROVIDER_UNAVAILABLE",
        ),
        provider=ProviderSummary(),
    )
    assert error.status is CaseResultStatus.ERROR

    with pytest.raises(ValidationError):
        CaseResult.model_validate(
            {
                **valid_case().model_dump(),
                "status": "SKIPPED",
            }
        )


def test_live_mode_rejects_fake_provider_calls() -> None:
    with pytest.raises(ValidationError, match="fake"):
        valid_run(
            mode=EvaluationMode.LIVE_GEMINI,
            cases=(valid_case(reached=True, provider_name="fake"),),
            metrics=MetricsBundle(
                extraction_quality=ExtractionQuality(
                    status=ExtractionQualityStatus.AVAILABLE,
                    reason="Real Gemini provider evidence is available.",
                )
            ),
        )


def test_live_mode_can_record_an_unreached_non_provider_scenario() -> None:
    result = valid_run(
        mode=EvaluationMode.LIVE_GEMINI,
        cases=(valid_case(reached=False, provider_name=None),),
        metrics=MetricsBundle(
            extraction_quality=ExtractionQuality(
                status=ExtractionQualityStatus.AVAILABLE,
                reason="Real Gemini provider evidence is available for reached cases.",
            )
        ),
    )
    assert result.cases[0].provider.calls == 0
    assert result.cases[0].provider.name is None


def test_provider_free_result_rejects_gemini_case_evidence() -> None:
    with pytest.raises(ValidationError, match="provider-free"):
        valid_run(cases=(valid_case(reached=True, provider_name="gemini"),))


def test_provider_free_result_rejects_gemini_model_identity() -> None:
    base = valid_run()
    with pytest.raises(ValidationError, match="provider-free"):
        EvaluationRunResult.model_validate(
            {
                **base.model_dump(),
                "run": {**base.run.model_dump(), "gemini_model": "gemini-test"},
            }
        )


def test_provider_free_result_rejects_available_pricing() -> None:
    base = valid_run()
    with pytest.raises(ValidationError, match="provider-free"):
        EvaluationRunResult.model_validate(
            {
                **base.model_dump(),
                "pricing": PricingStatus(
                    status="AVAILABLE", pricing_snapshot_id="pricing-2026-10", model="gemini-test"
                ).model_dump(),
            }
        )


def test_provider_free_result_rejects_numeric_model_cost() -> None:
    base = valid_run()
    with pytest.raises(ValidationError, match="provider-free"):
        EvaluationRunResult.model_validate(
            {
                **base.model_dump(),
                "metrics": MetricsBundle(
                    extraction_quality=valid_quality(),
                    cost=CostMetrics(estimated_model_cost_per_initial_order=Decimal("0.01")),
                ).model_dump(),
            }
        )


def test_provider_free_result_rejects_gemini_called_orders() -> None:
    with pytest.raises(ValidationError, match="provider-free"):
        EvaluationRunResult.model_validate(
            {
                **valid_run().model_dump(),
                "metrics": MetricsBundle(
                    extraction_quality=valid_quality(),
                    cost=CostMetrics(gemini_called_order_count=1),
                ).model_dump(),
            }
        )


def test_duration_contract_uses_named_decimal_milliseconds() -> None:
    result = valid_run(
        cases=(
            CaseResult(
                case_id="normal-001",
                status=CaseResultStatus.PASS,
                durations_ms=DurationSummary(
                    parse_ms=Decimal("1.234"),
                    deterministic_validation_ms=Decimal("2.345"),
                    provider_free_intake_ms=Decimal("3.456"),
                    live_gemini_call_ms=None,
                ),
            ),
        )
    )
    durations = result.model_dump(mode="json")["cases"][0]["durations_ms"]

    assert set(durations) == {
        "parse_ms",
        "deterministic_validation_ms",
        "provider_free_intake_ms",
        "live_gemini_call_ms",
    }
    assert durations["parse_ms"] == "1.234"


@pytest.mark.parametrize("duration", [Decimal("-0.001"), Decimal("NaN"), Decimal("Infinity")])
def test_duration_contract_rejects_negative_or_non_finite_values(duration: Decimal) -> None:
    with pytest.raises(ValidationError):
        DurationSummary(parse_ms=duration)


def test_duration_contract_rejects_old_generic_duration_names() -> None:
    with pytest.raises(ValidationError):
        DurationSummary.model_validate({"validation_ms": 1})


def test_run_identity_contains_command_and_future_environment_slots() -> None:
    run = valid_run().model_dump(mode="json")["run"]

    assert run["command"] == "make evaluate"
    assert run["dependency_lock_identity"] == "uv.lock"
    assert run["database_version"] == "PostgreSQL 16"


@pytest.mark.parametrize(
    "failure_code",
    [
        "PROVIDER_UNAVAILABLE",
        "bad provider response",
        "raw\nexception",
        "Bearer secret",
        "x" * 65,
    ],
)
def test_failure_code_is_a_bounded_sanitized_identifier(failure_code: str) -> None:
    if failure_code == "PROVIDER_UNAVAILABLE":
        actual = CaseActual(parse=CaseResultStatus.ERROR, failure_code=failure_code)
        assert (
            CaseResult(
                case_id="broken-001",
                status=CaseResultStatus.ERROR,
                actual=actual,
                provider=ProviderSummary(),
            ).actual.failure_code
            == failure_code
        )
    else:
        with pytest.raises(ValidationError):
            actual = CaseActual(parse=CaseResultStatus.ERROR, failure_code=failure_code)
            CaseResult(
                case_id="broken-001",
                status=CaseResultStatus.ERROR,
                actual=actual,
                provider=ProviderSummary(),
            )


@pytest.mark.parametrize(
    "secret_field,secret_value",
    [
        ("raw_document_bytes", b"private document"),
        ("raw_document_text", "private document"),
        ("api_key", "AIza-secret"),
        ("authorization", "Bearer secret"),
        ("metadata", {"token": "secret"}),
    ],
)
def test_result_contract_rejects_raw_documents_and_secret_metadata(
    secret_field: str, secret_value: object
) -> None:
    payload = valid_run().model_dump(mode="python")
    payload[secret_field] = secret_value

    with pytest.raises(ValidationError):
        EvaluationRunResult.model_validate(payload)


def test_result_serialization_is_json_safe_and_does_not_emit_internal_payloads() -> None:
    encoded = valid_run().model_dump_json()

    assert "raw_document" not in encoded
    assert "api_key" not in encoded
    assert "authorization" not in encoded
    assert '"git_sha"' in encoded


def test_human_readable_limitations_are_bounded_and_sanitized() -> None:
    with pytest.raises(ValidationError):
        EvaluationRunResult.model_validate(
            {**valid_run().model_dump(), "limitations": ["Traceback: secret body"]}
        )

    with pytest.raises(ValidationError):
        PricingStatus(status="ERROR", reason="Bearer secret")


def test_rate_metric_rejects_numerator_above_denominator() -> None:
    with pytest.raises(ValidationError, match="numerator"):
        RateMetric(numerator=2, denominator=1, value=Decimal("1"))


def test_rate_metric_requires_zero_numerator_for_zero_denominator() -> None:
    with pytest.raises(ValidationError, match="denominator"):
        RateMetric(numerator=1, denominator=0, value=None)

    assert RateMetric(numerator=0, denominator=0, value=None).value is None
