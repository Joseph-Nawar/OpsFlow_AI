from __future__ import annotations

import json
import subprocess
import traceback
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from opsflow.evaluation.artifacts import (
    ArtifactValidationError,
    render_markdown_from_json,
    validate_result_json,
    write_result_json,
)
from opsflow.evaluation.commands import run_evaluation
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
            run_id="8f371683-85f2-4a01-9fe7-a6b1f793b149",
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
            database=DatabaseMetadata(engine="postgresql", isolated=True),
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


def valid_live_result() -> EvaluationRunResult:
    result = valid_result().model_dump(mode="python")
    result["run"]["mode"] = EvaluationMode.LIVE_GEMINI
    result["run"]["gemini_model"] = "gemini-3.8-flash"
    result["metrics"]["cost"] = CostMetrics(status="ERROR").model_dump()
    result["pricing"] = PricingStatus(
        status="ERROR",
        model="gemini-3.8-flash",
        reason="No verified pricing snapshot was selected; numeric model cost may be unavailable.",
    ).model_dump()
    return EvaluationRunResult.model_validate(result)


def _mock_command_environment(monkeypatch, tmp_path: Path, result: EvaluationRunResult):
    from sqlalchemy.pool import NullPool

    import opsflow.evaluation.commands as commands

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    observed: dict[str, object] = {}

    engine_options: dict[str, object] = {}

    def fake_create_async_engine(_url, **kwargs):
        engine_options.update(kwargs)
        return FakeEngine()

    monkeypatch.setattr(commands, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(commands, "_reset_database", lambda *_args: None)
    monkeypatch.setattr(commands, "confirm_current_migration_head", lambda *_args: None)
    monkeypatch.setattr(commands, "_read_server_version", lambda _engine: "PostgreSQL 16")
    monkeypatch.setattr(commands, "_build_session_factory", lambda _engine: object())
    monkeypatch.setattr(commands, "build_orchestration_runtime", lambda *_args, **_kwargs: object())

    async def fake_run_corpus(_sessions, manifest, _runtime, mode, **kwargs):
        observed["mode"] = mode
        observed["case_count"] = len(manifest.cases)
        observed.update(kwargs)
        return result

    monkeypatch.setattr(commands, "run_corpus", fake_run_corpus)
    observed["artifacts_directory"] = tmp_path / "results"
    observed["expected_pool_class"] = NullPool
    observed["engine_options"] = engine_options
    return observed


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


@pytest.mark.parametrize(
    ("field", "synthetic_secret"),
    [
        ("run_id", "ghp_TESTONLY0000000000000000000000000000"),
        ("gemini_model", "ghp_TESTONLY0000000000000000000000000000"),
        ("platform", "host-AKIAAAAAAAAAAAAAAAAA"),
    ],
)
def test_metadata_credentials_are_rejected_without_echoing_secret(
    field: str, synthetic_secret: str
) -> None:
    base_result = valid_live_result() if field == "gemini_model" else valid_result()
    payload = base_result.model_dump(mode="json")
    payload["run"][field] = synthetic_secret

    with pytest.raises(ArtifactValidationError) as error:
        validate_result_json(payload)

    assert synthetic_secret not in str(error.value)
    assert synthetic_secret not in "".join(traceback.format_exception(error.value))
    with pytest.raises(ArtifactValidationError):
        render_markdown_from_json(json.dumps(payload))


def test_result_json_allows_the_controlled_prompt_injection_corpus_tag() -> None:
    payload = valid_result().model_dump(mode="json")
    payload["corpus"]["tag_counts"] = {"prompt_injection": 1}

    result = validate_result_json(payload)

    assert result.corpus.tag_counts == {"prompt_injection": 1}


def test_markdown_does_not_invent_release_gate_results() -> None:
    report = render_markdown_from_json(valid_result().model_dump_json())

    assert "No release gate results are present in this JSON result." in report
    assert "PASS" not in report


def test_markdown_escapes_untrusted_cell_content() -> None:
    payload = valid_result().model_dump(mode="json")
    payload["run"]["platform"] = "platform | [label](reference)"

    report = render_markdown_from_json(json.dumps(payload))

    assert "| Platform | platform \\| \\[label\\]\\(reference\\) |" in report


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


def test_provider_free_command_needs_no_gemini_settings_and_writes_json_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed = _mock_command_environment(monkeypatch, tmp_path, valid_result())

    artifacts = run_evaluation(
        EvaluationMode.PROVIDER_FREE,
        environ={
            "OPSFLOW_EVALUATION_DATABASE_URL": (
                "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:55432/opsflow_evaluation"
            )
        },
        results_directory=observed["artifacts_directory"],
    )

    assert observed["mode"] is EvaluationMode.PROVIDER_FREE
    assert observed["case_count"] == 36
    assert observed["gemini_provider_factory"] is None
    assert observed["engine_options"] == {"poolclass": observed["expected_pool_class"]}
    assert artifacts.json_path.exists()
    assert artifacts.markdown_path.exists()
    assert artifacts.markdown_path.read_text(encoding="utf-8") == render_markdown_from_json(
        artifacts.json_path
    )


def test_live_command_accepts_missing_pricing_without_calling_the_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import opsflow.evaluation.commands as commands

    observed = _mock_command_environment(monkeypatch, tmp_path, valid_live_result())
    monkeypatch.setattr(commands, "_load_optional_pricing_snapshot", lambda: None)
    environment = {
        "OPSFLOW_EVALUATION_LIVE_GEMINI": "1",
        "OPSFLOW_GEMINI_API_KEY": "test-key-not-used",
        "OPSFLOW_GEMINI_MODEL": "gemini-3.8-flash",
        "OPSFLOW_GEMINI_TIMEOUT_SECONDS": "30",
        "OPSFLOW_EVALUATION_DATABASE_URL": (
            "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:55432/opsflow_evaluation"
        ),
    }

    artifacts = run_evaluation(
        EvaluationMode.LIVE_GEMINI,
        environ=environment,
        results_directory=observed["artifacts_directory"],
    )

    assert observed["mode"] is EvaluationMode.LIVE_GEMINI
    assert observed["configured_model"] == "gemini-3.8-flash"
    assert observed["pricing_snapshot"] is None
    assert callable(observed["gemini_provider_factory"])
    assert observed["engine_options"] == {"poolclass": observed["expected_pool_class"]}
    assert artifacts.result.pricing.status == "ERROR"
    assert artifacts.result.metrics.cost.estimated_model_cost_per_initial_order is None
    assert artifacts.json_path.exists()
