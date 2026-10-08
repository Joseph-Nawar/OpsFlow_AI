from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from opsflow.evaluation.corpus import EvaluationBusinessDataProvider, load_catalog, load_manifest
from opsflow.evaluation.models import (
    CaseActual,
    CaseCategory,
    CaseResult,
    CaseResultStatus,
    CaseScores,
    EvaluationMode,
    ProviderSummary,
    SideEffectDetail,
    SideEffectSummary,
)
from opsflow.evaluation.runner import run_corpus
from opsflow.evaluation.scoring import evaluate_release_gates
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.review.composition import ReviewDateProvider
from opsflow.validation.policy import ValidationPolicy


class _FixedDateProvider(ReviewDateProvider):
    def current_date(self) -> date:
        return date(2026, 10, 10)


@pytest.fixture
def full_corpus_session_factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    configured_url = os.environ.get("OPSFLOW_M11C_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("full M11C corpus test requires OPSFLOW_M11C_TEST_DATABASE_URL")
    parsed_url = make_url(configured_url)
    if parsed_url.get_backend_name() != "postgresql":
        pytest.fail("full M11C corpus test requires PostgreSQL")
    if parsed_url.database is None or not parsed_url.database.startswith("opsflow_m11c_"):
        pytest.fail("full M11C corpus test requires a separately named disposable database")
    engine = create_async_engine(configured_url, poolclass=NullPool)

    async def clear() -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE "
                    "notification_deliveries, order_syncs, validation_issues, "
                    "extraction_snapshots, review_revisions, audit_events, "
                    "order_lines, source_documents, order_creation_idempotency, orders "
                    "RESTART IDENTITY CASCADE"
                )
            )

    asyncio.run(clear())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


def _candidate_results() -> tuple[CaseResult, ...]:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = []
    for case in manifest.cases:
        is_approval = case.approval is not None
        is_duplicate = case.primary_category is CaseCategory.DUPLICATE
        results.append(
            CaseResult(
                case_id=case.case_id,
                status=CaseResultStatus.PASS,
                actual=CaseActual(
                    route=case.expected_validation.route if case.expected_validation else None,
                    approval_level=(
                        case.expected_validation.approval_level
                        if case.expected_validation
                        else None
                    ),
                    pre_approval_state=(
                        CaseActual().pre_approval_state
                        if case.expected_validation is None
                        else case.expected_validation.pre_approval_state
                    ),
                    idempotent_replay=is_duplicate,
                    creation_disposition=(
                        case.replay.expected_creation_disposition if case.replay else None
                    ),
                    intake_execution=(
                        case.replay.expected_intake_execution if case.replay else None
                    ),
                    external_execution="COMPLETED" if is_approval else "NOT_RUN",
                    external_execution_eligible=is_approval,
                ),
                scores=CaseScores(
                    validation_match=(
                        True
                        if case.primary_category is CaseCategory.DETERMINISTIC_VIOLATION
                        else None
                    )
                ),
                provider=ProviderSummary(name="fake", calls=1),
                side_effects=SideEffectSummary(
                    logical_external_objects=SideEffectDetail(
                        status="COMPLETED" if is_approval else "NOT_RUN",
                        count=4 if is_approval else 0,
                    )
                ),
            )
        )
    return tuple(results)


def test_all_five_release_gates_require_explicit_pass_evidence() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    summary = evaluate_release_gates(manifest, _candidate_results())

    assert len(summary.results) == 5
    assert summary.all_passed is True
    assert all(result.status == "PASS" for result in summary.results)
    assert all(result.failing_case_ids == () for result in summary.results)


def test_duplicate_graph_failure_is_reported_and_cannot_pass() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    duplicate = next(
        index
        for index, case in enumerate(manifest.cases)
        if case.primary_category is CaseCategory.DUPLICATE
    )
    results[duplicate] = results[duplicate].model_copy(
        update={
            "side_effects": SideEffectSummary(
                logical_external_objects=SideEffectDetail(status="COMPLETED", count=1)
            )
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))

    duplicate_gate = next(
        result for result in summary.results if result.gate_id == "DUPLICATE_BLOCKING"
    )
    assert duplicate_gate.status == "FAIL"
    assert duplicate_gate.failing_case_ids == (manifest.cases[duplicate].case_id,)
    assert summary.all_passed is False


def test_missing_gate_evidence_is_error_not_pass() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = _candidate_results()[:-1]

    summary = evaluate_release_gates(manifest, results)

    assert summary.all_passed is False
    assert any(result.status == "ERROR" for result in summary.results)


def test_real_provider_free_corpus_has_all_cases_and_all_gates_pass(
    full_corpus_session_factory,
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    catalog = load_catalog(Path("evals/corpus/v1/trusted-data/catalog.json"))
    runtime = OrchestrationRuntime(
        extraction_provider_factory=lambda: None,
        business_data_provider=EvaluationBusinessDataProvider(catalog),
        policy=ValidationPolicy(
            supported_currencies=("USD",),
            price_tolerance_fraction=Decimal("0.05"),
            high_value_threshold=Decimal("1000"),
        ),
        date_provider=_FixedDateProvider(),
        review_base_url="https://review.invalid/m11c",
    )

    result = asyncio.run(
        run_corpus(
            full_corpus_session_factory,
            manifest,
            runtime,
            EvaluationMode.PROVIDER_FREE,
        )
    )

    assert result.corpus.case_count == 36
    assert len(result.cases) == 36
    assert result.run.corpus_version == "3.0.0"
    assert result.metrics.extraction_quality.status.value == "NOT_APPLICABLE"
    assert result.release_gates.all_passed is True
    assert len(result.release_gates.results) == 5
    assert all(gate.status == "PASS" for gate in result.release_gates.results)
