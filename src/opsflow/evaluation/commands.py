"""Explicit provider-free and opt-in live evaluation command orchestration."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.gemini import GeminiConfig, GeminiProvider
from opsflow.orchestration.composition import OrchestrationRuntime, build_orchestration_runtime
from opsflow.settings import Settings

from .artifacts import write_markdown_from_json, write_result_json
from .corpus import load_manifest
from .database import (
    EvaluationDatabaseConfig,
    EvaluationDatabaseSafetyError,
    assert_evaluation_database_isolated,
    confirm_current_migration_head,
    reset_evaluation_application_data,
)
from .measurements import (
    EvaluationMeasurements,
    PricingSnapshot,
    load_pricing_snapshot,
)
from .models import CorpusManifest, EvaluationMode, EvaluationRunResult
from .runner import run_corpus

CORPUS_ROOT = Path("evals/corpus/v1")
PRICING_SNAPSHOT_PATH = Path("evals/pricing/2026-10-10-google-gemini-3.8-flash-standard-paid.json")
EXPECTED_MIGRATION_HEAD = "0007_phase7_intake_ownership"
EXPECTED_CORPUS_VERSION = "3.0.0"
EXPECTED_CASE_COUNT = 36
RESULTS_DIRECTORY = Path("evals/results")


class LivePreflightError(ValueError):
    """Raised when an explicitly requested live Gemini run is not configured."""


@dataclass(frozen=True, slots=True)
class EvaluationArtifacts:
    result: EvaluationRunResult
    json_path: Path
    markdown_path: Path


def validate_live_preflight(environ: Mapping[str, str]) -> GeminiConfig:
    """Validate the four approved live requirements before corpus or DB work."""

    if environ.get("OPSFLOW_EVALUATION_LIVE_GEMINI") != "1":
        raise LivePreflightError("live evaluation requires OPSFLOW_EVALUATION_LIVE_GEMINI=1")
    api_key = environ.get("OPSFLOW_GEMINI_API_KEY")
    if api_key is None or not api_key.strip():
        raise LivePreflightError("live evaluation requires a nonblank OPSFLOW_GEMINI_API_KEY")
    model = environ.get("OPSFLOW_GEMINI_MODEL")
    if model is None or not model.strip():
        raise LivePreflightError("live evaluation requires a nonblank OPSFLOW_GEMINI_MODEL")
    raw_timeout = environ.get("OPSFLOW_GEMINI_TIMEOUT_SECONDS")
    if raw_timeout is None or not raw_timeout.strip():
        raise LivePreflightError(
            "live evaluation requires OPSFLOW_GEMINI_TIMEOUT_SECONDS to be finite and positive"
        )
    try:
        timeout_seconds = float(raw_timeout)
        config = GeminiConfig(api_key, model, timeout_seconds)
    except (TypeError, ValueError, OverflowError) as error:
        raise LivePreflightError(
            "live evaluation requires a nonblank key and model plus a finite positive timeout"
        ) from error
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise LivePreflightError(
            "live evaluation requires OPSFLOW_GEMINI_TIMEOUT_SECONDS to be finite and positive"
        )
    return config


def _load_optional_pricing_snapshot() -> PricingSnapshot | None:
    try:
        return load_pricing_snapshot(PRICING_SNAPSHOT_PATH)
    except (OSError, ValueError):
        return None


def _reset_database(config: EvaluationDatabaseConfig, engine: AsyncEngine) -> None:
    asyncio.run(reset_evaluation_application_data(config, engine))


def _build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _server_version(engine: AsyncEngine) -> str:
    async with engine.connect() as connection:
        version = await connection.scalar(text("SHOW server_version"))
    if not isinstance(version, str) or not version:
        raise EvaluationDatabaseSafetyError("PostgreSQL server version could not be verified")
    major_version = version.split(".", maxsplit=1)[0]
    if not major_version.isdigit():
        raise EvaluationDatabaseSafetyError("PostgreSQL server version could not be verified")
    return f"PostgreSQL {major_version}"


def _read_server_version(engine: AsyncEngine) -> str:
    return asyncio.run(_server_version(engine))


def _run_corpus(
    session_factory: async_sessionmaker[AsyncSession],
    manifest: CorpusManifest,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
    *,
    measurements: EvaluationMeasurements,
    gemini_config: GeminiConfig | None,
    pricing_snapshot: PricingSnapshot | None,
) -> EvaluationRunResult:
    provider_factory = None
    if gemini_config is not None:

        def create_gemini_provider() -> GeminiProvider:
            return GeminiProvider(gemini_config)

        provider_factory = create_gemini_provider
    return asyncio.run(
        run_corpus(
            session_factory,
            manifest,
            runtime,
            mode,
            measurements=measurements,
            gemini_provider_factory=provider_factory,
            configured_model=gemini_config.model if gemini_config is not None else None,
            pricing_snapshot=pricing_snapshot,
        )
    )


def run_evaluation(
    mode: EvaluationMode,
    *,
    environ: Mapping[str, str] | None = None,
    results_directory: Path = RESULTS_DIRECTORY,
) -> EvaluationArtifacts:
    """Guard, clean, run, and publish one full evaluation mode."""

    process_environment = os.environ if environ is None else environ
    settings = (
        Settings()
        if mode is EvaluationMode.LIVE_GEMINI
        else Settings(
            gemini_api_key=None,
            gemini_model=None,
            gemini_timeout_seconds=None,
        )
    )
    preflight_environment = dict(process_environment)
    if environ is None and mode is EvaluationMode.LIVE_GEMINI:
        if "OPSFLOW_GEMINI_API_KEY" not in preflight_environment and settings.gemini_api_key:
            preflight_environment["OPSFLOW_GEMINI_API_KEY"] = (
                settings.gemini_api_key.get_secret_value()
            )
        if "OPSFLOW_GEMINI_MODEL" not in preflight_environment and settings.gemini_model:
            preflight_environment["OPSFLOW_GEMINI_MODEL"] = settings.gemini_model
        if (
            "OPSFLOW_GEMINI_TIMEOUT_SECONDS" not in preflight_environment
            and settings.gemini_timeout_seconds is not None
        ):
            preflight_environment["OPSFLOW_GEMINI_TIMEOUT_SECONDS"] = str(
                settings.gemini_timeout_seconds
            )
    # This gate intentionally precedes corpus loading, DB configuration, and cleanup.
    gemini_config = (
        validate_live_preflight(preflight_environment)
        if mode is EvaluationMode.LIVE_GEMINI
        else None
    )

    manifest = load_manifest(CORPUS_ROOT)
    if manifest.corpus_version != EXPECTED_CORPUS_VERSION:
        raise ValueError("the active evaluation corpus version is not 3.0.0")
    if len(manifest.cases) != EXPECTED_CASE_COUNT:
        raise ValueError("the active evaluation corpus must contain exactly 36 cases")

    database_config = EvaluationDatabaseConfig.from_environment(
        process_environment,
        settings.database_url,
        process_environment.get("OPSFLOW_MIGRATION_TEST_DATABASE_URL"),
    )
    assert_evaluation_database_isolated(database_config)
    # Database helpers run their short async units with separate event loops.
    # Do not return an asyncpg connection from one loop to another.
    engine = create_async_engine(database_config.evaluation_url, poolclass=NullPool)
    try:
        _reset_database(database_config, engine)
        confirm_current_migration_head(Config("alembic.ini"), EXPECTED_MIGRATION_HEAD)
        database_version = _read_server_version(engine)
        session_factory = _build_session_factory(engine)
        if gemini_config is None:

            def create_unused_fake_provider() -> FakeProvider:
                return FakeProvider(())

            runtime = build_orchestration_runtime(
                settings,
                extraction_provider_factory=create_unused_fake_provider,
            )
            pricing_snapshot = None
        else:

            def create_live_gemini_provider() -> GeminiProvider:
                return GeminiProvider(gemini_config)

            runtime = build_orchestration_runtime(
                settings,
                extraction_provider_factory=create_live_gemini_provider,
            )
            pricing_snapshot = _load_optional_pricing_snapshot()

        measurements = EvaluationMeasurements()
        result = _run_corpus(
            session_factory,
            manifest,
            runtime,
            mode,
            measurements=measurements,
            gemini_config=gemini_config,
            pricing_snapshot=pricing_snapshot,
        )
        result = result.model_copy(
            update={"run": result.run.model_copy(update={"database_version": database_version})}
        )
        results_directory = Path(results_directory)
        result_path = results_directory / f"{mode.value}-{result.run.run_id}.json"
        report_path = results_directory / f"{mode.value}-{result.run.run_id}.md"
        write_result_json(result, result_path)
        write_markdown_from_json(result_path, report_path)
        return EvaluationArtifacts(result, result_path, report_path)
    finally:
        asyncio.run(engine.dispose())


def _successful_result(artifacts: EvaluationArtifacts) -> bool:
    result = artifacts.result
    if result.run.mode is EvaluationMode.PROVIDER_FREE:
        return (
            result.corpus.case_count == EXPECTED_CASE_COUNT
            and result.release_gates.all_passed is True
        )
    return (
        result.metrics.provider_usage.gemini_call_count > 0
        and result.metrics.provider_usage.failed_call_count == 0
        and all(case.status.value != "ERROR" for case in result.cases)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OpsFlow Phase 11 evaluation corpus.")
    parser.add_argument("mode", choices=("provider-free", "live-gemini"))
    arguments = parser.parse_args(argv)
    mode = (
        EvaluationMode.PROVIDER_FREE
        if arguments.mode == "provider-free"
        else EvaluationMode.LIVE_GEMINI
    )
    try:
        artifacts = run_evaluation(mode)
    except LivePreflightError as error:
        print(str(error))
        return 2
    except EvaluationDatabaseSafetyError:
        print("Evaluation database isolation, connection, or migration verification failed.")
        return 2
    except Exception as error:
        print(
            f"Evaluation failed before a successful result was produced ({type(error).__name__})."
        )
        return 1
    print(f"JSON: {artifacts.json_path}")
    print(f"Markdown: {artifacts.markdown_path}")
    if not _successful_result(artifacts):
        print("Evaluation result contains failed gates or unsuccessful provider evidence.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EvaluationArtifacts",
    "LivePreflightError",
    "main",
    "run_evaluation",
    "validate_live_preflight",
]
