from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from opsflow.evaluation.models import (
    CaseResult,
    CaseResultStatus,
    ContractEvidence,
    EnvironmentMetadata,
    EvaluationMode,
    EvaluationRunResult,
    ExtractionQuality,
    ExtractionQualityStatus,
    RateMetric,
)


def valid_quality() -> ExtractionQuality:
    return ExtractionQuality(
        status=ExtractionQualityStatus.NOT_APPLICABLE,
        complete_exact_match=None,
        field_tp=None,
        field_fp=None,
        field_fn=None,
        precision=None,
        recall=None,
        f1=None,
        per_field=None,
        reached_live_gemini_case_count=0,
        reason="No real model was evaluated in provider-free mode.",
    )


def valid_run() -> EvaluationRunResult:
    return EvaluationRunResult(
        run_id="run-001",
        started_at=datetime(2026, 10, 8, tzinfo=UTC),
        finished_at=datetime(2026, 10, 8, 0, 1, tzinfo=UTC),
        git_sha="a" * 40,
        corpus_version="1.0.0",
        result_schema_version="1.0",
        mode=EvaluationMode.PROVIDER_FREE,
        command="make evaluate",
        extraction_quality=valid_quality(),
        cases=(
            CaseResult(
                case_id="normal-001",
                status=CaseResultStatus.SUCCEEDED,
                provider_reached=False,
                failure_code=None,
            ),
        ),
    )


def test_provider_free_result_is_explicitly_not_applicable_for_model_quality() -> None:
    result = valid_run().model_copy(
        update={
            "cases": (
                CaseResult(
                    case_id="normal-001",
                    status=CaseResultStatus.SUCCEEDED,
                    provider_reached=False,
                    failure_code=None,
                    contract_evidence=ContractEvidence(
                        parser_succeeded=True,
                        evidence_grounded=True,
                        scripted_provider_call_count=1,
                    ),
                ),
            )
        }
    )
    payload = result.model_dump(mode="json")

    assert payload["mode"] == "provider_free"
    assert payload["cases"][0]["contract_evidence"]["parser_succeeded"] is True
    assert "accuracy" not in payload["cases"][0]["contract_evidence"]
    assert payload["extraction_quality"]["status"] == "NOT_APPLICABLE"
    assert payload["extraction_quality"]["reason"]
    assert payload["extraction_quality"]["precision"] is None


def test_provider_free_result_cannot_publish_a_scripted_extraction_score() -> None:
    with pytest.raises(ValidationError, match="NOT_APPLICABLE"):
        EvaluationRunResult(
            run_id="run-001",
            started_at=datetime(2026, 10, 8, tzinfo=UTC),
            finished_at=datetime(2026, 10, 8, 0, 1, tzinfo=UTC),
            git_sha="a" * 40,
            corpus_version="1.0.0",
            result_schema_version="1.0",
            mode=EvaluationMode.PROVIDER_FREE,
            command="make evaluate",
            extraction_quality=ExtractionQuality(
                status=ExtractionQualityStatus.AVAILABLE,
                complete_exact_match=RateMetric(numerator=1, denominator=1, value=Decimal("1")),
                reason="scripted provider matched",
            ),
            cases=(),
        )


def test_not_applicable_quality_cannot_contain_a_rate() -> None:
    with pytest.raises(ValidationError, match="NOT_APPLICABLE"):
        ExtractionQuality(
            status=ExtractionQualityStatus.NOT_APPLICABLE,
            complete_exact_match=RateMetric(numerator=1, denominator=1, value=Decimal("1")),
            reason="No real model was evaluated.",
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
    result = valid_run()
    encoded = result.model_dump_json()

    assert "raw_document" not in encoded
    assert "api_key" not in encoded
    assert "authorization" not in encoded
    assert '"git_sha"' in encoded


def test_failed_case_requires_a_bounded_failure_code() -> None:
    with pytest.raises(ValidationError, match="failure_code"):
        CaseResult(
            case_id="broken-001",
            status=CaseResultStatus.FAILED,
            provider_reached=False,
            failure_code=None,
        )


def test_live_result_serializes_real_provider_reachability_and_attempt_count() -> None:
    live_quality = ExtractionQuality(
        status=ExtractionQualityStatus.AVAILABLE,
        reason="Real Gemini provider evidence is available for reached cases.",
    )
    result = EvaluationRunResult(
        run_id="run-live-001",
        started_at=datetime(2026, 10, 8, tzinfo=UTC),
        finished_at=datetime(2026, 10, 8, 0, 1, tzinfo=UTC),
        git_sha="b" * 40,
        corpus_version="1.0.0",
        result_schema_version="1.0",
        mode=EvaluationMode.LIVE_GEMINI,
        command="make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1",
        environment=EnvironmentMetadata(gemini_model="gemini-test"),
        extraction_quality=live_quality,
        cases=(
            CaseResult(
                case_id="normal-001",
                status=CaseResultStatus.SUCCEEDED,
                provider_reached=True,
                provider_name="gemini",
                provider_call_count=1,
            ),
            CaseResult(
                case_id="security-001",
                status=CaseResultStatus.SKIPPED,
                provider_reached=False,
                provider_name=None,
                provider_call_count=0,
            ),
        ),
    )

    payload = result.model_dump(mode="json")

    assert payload["cases"][0]["provider_name"] == "gemini"
    assert payload["cases"][0]["provider_reached"] is True
    assert payload["cases"][0]["provider_call_count"] == 1
    assert payload["cases"][1]["provider_reached"] is False
    assert payload["cases"][1]["provider_call_count"] == 0
