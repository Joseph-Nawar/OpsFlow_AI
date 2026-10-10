from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from opsflow.evaluation.artifacts import (
    render_markdown_from_json,
    validate_result_json,
    write_result_json,
)
from opsflow.evaluation.models import (
    CorpusComposition,
    CostMetrics,
    DatabaseMetadata,
    EvaluationMode,
    EvaluationRunResult,
    ExtractionQuality,
    ExtractionQualityStatus,
    MetricsBundle,
    PricingStatus,
    ReleaseGateSummary,
    RunMetadata,
)


def valid_result() -> EvaluationRunResult:
    return EvaluationRunResult(
        run=RunMetadata(
            run_id="run-artifact-test",
            mode=EvaluationMode.PROVIDER_FREE,
            started_at_utc=datetime(2026, 10, 10, tzinfo=UTC),
            finished_at_utc=datetime(2026, 10, 10, 0, 1, tzinfo=UTC),
            git_sha="a" * 40,
            corpus_version="3.0.0",
            command="make evaluate",
            dependency_lock_identity="uv.lock",
            database_version="PostgreSQL 16",
            python_version="3.12.13",
            platform="macOS-15.0-arm64-arm-64bit",
            cpu_architecture="arm64",
            database=DatabaseMetadata(engine="PostgreSQL 16", isolated=True),
        ),
        corpus=CorpusComposition(
            case_count=0,
            primary_category_counts={},
            format_counts={},
            tag_counts={},
        ),
        cases=(),
        metrics=MetricsBundle(
            extraction_quality=ExtractionQuality(
                status=ExtractionQualityStatus.NOT_APPLICABLE,
                reason="No real model was evaluated in provider-free mode.",
            ),
            cost=CostMetrics(status="NOT_APPLICABLE"),
        ),
        pricing=PricingStatus(status="NOT_APPLICABLE"),
        release_gates=ReleaseGateSummary(all_passed=False),
    )


def test_markdown_is_rendered_from_saved_json_without_source_files(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("synthetic private source contents", encoding="utf-8")
    json_path = tmp_path / "result.json"
    write_result_json(valid_result(), json_path)
    selected_json = json_path.read_text(encoding="utf-8")

    source.unlink()
    first_report = render_markdown_from_json(selected_json)
    second_report = render_markdown_from_json(selected_json)

    assert first_report == second_report
    assert "3.0.0" in first_report
    assert "NOT_APPLICABLE" in first_report
    assert "synthetic private source contents" not in first_report


def test_result_json_has_nine_contract_keys_and_excludes_internal_payloads(tmp_path: Path) -> None:
    json_path = tmp_path / "result.json"
    write_result_json(valid_result(), json_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert set(payload) == {
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
    assert "expected_extraction" not in json_path.read_text(encoding="utf-8")
    assert "predicted_extraction" not in json_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(raw_document_text="private source"),
        lambda payload: payload["run"].update(command="Bearer secret"),
        lambda payload: payload["run"].update(platform="/Users/private-machine"),
        lambda payload: payload["metrics"].update(provider_response="raw response"),
    ],
)
def test_result_json_rejects_raw_or_private_payloads(mutate) -> None:
    payload = valid_result().model_dump(mode="json")
    mutate(payload)

    with pytest.raises((ValidationError, ValueError)):
        validate_result_json(payload)


def test_markdown_does_not_invent_release_gate_results() -> None:
    report = render_markdown_from_json(valid_result().model_dump_json())

    assert "No release gate results are present in this JSON result." in report
    assert "PASS" not in report


def test_markdown_escapes_untrusted_cell_content() -> None:
    payload = valid_result().model_dump(mode="json")
    payload["run"]["run_id"] = "run | [label](reference)"

    report = render_markdown_from_json(json.dumps(payload))

    assert "| Run ID | run \\| \\[label\\]\\(reference\\) |" in report


def test_ad_hoc_artifacts_are_ignored_and_reference_path_is_explicit() -> None:
    generated = subprocess.run(
        ["git", "check-ignore", "--no-index", "evals/results/local-result.json"],
        check=False,
        capture_output=True,
        text=True,
    )
    reference = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "docs/evaluation/reference/phase-11-provider-free-baseline.json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert generated.returncode == 0
    assert reference.returncode == 1
