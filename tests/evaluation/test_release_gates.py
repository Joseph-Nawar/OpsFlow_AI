from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from db_support import clear_m11c_application_data
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from opsflow.evaluation.corpus import EvaluationBusinessDataProvider, load_catalog, load_manifest
from opsflow.evaluation.models import (
    AuthorityEvidence,
    CaseActual,
    CaseCategory,
    CaseResult,
    CaseResultStatus,
    CaseScores,
    EvaluationMode,
    ProviderSummary,
    ReplayEvidence,
    SideEffectDetail,
    SideEffectSummary,
)
from opsflow.evaluation.runner import run_corpus
from opsflow.evaluation.scoring import build_routing_metrics, evaluate_release_gates
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

    asyncio.run(clear_m11c_application_data(engine))
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
        is_recovery = case.recovery is not None
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
                    replay=(
                        ReplayEvidence(
                            creation_disposition=case.replay.expected_creation_disposition,
                            intake_execution=case.replay.expected_intake_execution,
                            seed_order_id="00000000-0000-0000-0000-000000000001",
                            replay_order_id="00000000-0000-0000-0000-000000000001",
                            authoritative_order_count=1,
                            provider_calls_before=1,
                            provider_calls_after=1,
                            notification_intents_before=0,
                            notification_intents_after=0,
                            order_sync_intents_before=0,
                            order_sync_intents_after=0,
                            logical_external_object_count=0,
                            provider_work_stood_down=True,
                        )
                        if is_duplicate
                        else None
                    ),
                    authority=AuthorityEvidence(
                        operator_context_bound=True,
                        approval_probe="PASS" if case.expected_validation else "NOT_APPLICABLE",
                        retry_probe="NOT_APPLICABLE",
                        notification_probe="PASS",
                        external_execution_probe="PASS",
                        direct_authority_violation_count=0,
                    ),
                ),
                scores=CaseScores(
                    validation_match=True if case.expected_validation else None,
                    reliability_match=True if (is_duplicate or is_recovery) else None,
                    replay_match=True if is_duplicate else None,
                    execution_safety_match=True,
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


def test_release_gate_numerators_are_violation_or_success_counts_as_specified() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    summary = evaluate_release_gates(manifest, _candidate_results())

    assert [
        (result.gate_id, result.numerator, result.denominator) for result in summary.results
    ] == [
        ("invalid_orders_executed_zero", 0, 13),
        ("deterministic_violation_routing_100", 7, 7),
        ("duplicate_blocking_100", 4, 4),
        ("malformed_security_safe_100", 4, 4),
        ("direct_llm_side_effects_zero", 0, 36),
    ]


def test_invalid_pass_through_mutation_is_a_single_violation() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    invalid_index = next(
        index
        for index, case in enumerate(manifest.cases)
        if case.expected_validation is not None
        and case.expected_validation.external_execution_eligible is False
    )
    results[invalid_index] = results[invalid_index].model_copy(
        update={
            "actual": results[invalid_index].actual.model_copy(
                update={
                    "external_execution": "COMPLETED",
                    "external_execution_eligible": True,
                }
            )
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))
    gate = next(
        result for result in summary.results if result.gate_id == "invalid_orders_executed_zero"
    )

    assert gate.numerator == 1
    assert gate.denominator == 13
    assert gate.status == "FAIL"
    assert gate.failing_case_ids == (manifest.cases[invalid_index].case_id,)


def test_direct_authority_mutation_is_a_single_violation() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    results[0] = results[0].model_copy(
        update={
            "actual": results[0].actual.model_copy(
                update={
                    "authority": AuthorityEvidence(
                        operator_context_bound=False,
                        approval_probe="FAIL",
                        retry_probe="FAIL",
                        notification_probe="FAIL",
                        external_execution_probe="FAIL",
                        direct_authority_violation_count=1,
                    )
                }
            )
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))
    gate = next(
        result for result in summary.results if result.gate_id == "direct_llm_side_effects_zero"
    )

    assert gate.numerator == 1
    assert gate.denominator == 36
    assert gate.status == "FAIL"
    assert gate.failing_case_ids == (manifest.cases[0].case_id,)


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
        result for result in summary.results if result.gate_id == "duplicate_blocking_100"
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


def test_m11c_routing_metrics_publish_full_correctness_and_reliability_rates() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = _candidate_results()
    gates = evaluate_release_gates(manifest, results)

    metrics = build_routing_metrics(manifest, results, gates)

    assert (metrics.full_routing_accuracy.numerator, metrics.full_routing_accuracy.denominator) == (
        14,
        14,
    )
    assert (metrics.invalid_pass_through.numerator, metrics.invalid_pass_through.denominator) == (
        0,
        13,
    )
    assert (metrics.duplicate_blocking.numerator, metrics.duplicate_blocking.denominator) == (4, 4)
    assert (metrics.retry_recovery.numerator, metrics.retry_recovery.denominator) == (3, 3)
    assert metrics.logical_duplication_count == 0


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
