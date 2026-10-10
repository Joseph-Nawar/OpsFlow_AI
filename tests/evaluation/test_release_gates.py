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
    LogicalObjectEvidence,
    LogicalObjectIdentity,
    ProviderSummary,
    ReplayEvidence,
    SideEffectDetail,
    SideEffectSummary,
)
from opsflow.evaluation.runner import run_corpus
from opsflow.evaluation.scoring import build_routing_metrics, evaluate_release_gates
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.review.composition import ReviewDateProvider
from opsflow.review.contracts import OperatorRole
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
        order_identity = "order:00000000-0000-0000-0000-000000000001"
        resulting_objects = (
            (
                LogicalObjectIdentity(
                    object_type="ODOO_ORDER",
                    stable_business_identity=order_identity,
                    object_identity="m11c-odoo-order-1",
                ),
                LogicalObjectIdentity(
                    object_type="HUBSPOT_COMPANY",
                    stable_business_identity="customer:CUST-0001",
                    object_identity="m11c-company-customer-1",
                ),
                LogicalObjectIdentity(
                    object_type="HUBSPOT_DEAL",
                    stable_business_identity=order_identity,
                    object_identity="m11c-deal-order-1",
                ),
                LogicalObjectIdentity(
                    object_type="HUBSPOT_ASSOCIATION",
                    stable_business_identity=order_identity,
                    object_identity="m11c-association-order-1",
                ),
            )
            if is_approval
            else ()
        )
        logical_evidence = LogicalObjectEvidence(
            executor_reached=is_approval,
            original_identities=resulting_objects[:1],
            resulting_identities=resulting_objects,
            original_object_count=len(resulting_objects[:1]),
            resulting_object_count=len(resulting_objects),
            logical_duplication_count=0,
            replay_created_extra_object=False,
            completed_step_rerun=False,
        )
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
                        operator_context_source="EVALUATOR_CONFIGURATION",
                        operator_context_actor="m11c-evaluator",
                        operator_roles_observed=tuple(
                            role
                            for role, applicable in (
                                (OperatorRole.REVIEWER, is_approval),
                                (OperatorRole.APPROVER, is_recovery),
                            )
                            if applicable
                        ),
                        approval_boundary_applicable=is_approval,
                        approval_probe="PASS" if is_approval else "NOT_APPLICABLE",
                        authorized_approval_observed=is_approval,
                        retry_boundary_applicable=is_recovery,
                        retry_probe="PASS" if is_recovery else "NOT_APPLICABLE",
                        authorized_retry_observed=is_recovery,
                        notification_context_observed=True,
                        notification_transition_count=1,
                        notification_intent_count=1,
                        notification_probe="PASS",
                        external_sync_context_observed=True,
                        external_sync_intent_count=int(is_approval),
                        external_sync_executor_reached=is_approval,
                        external_execution_authorized=True if is_approval else None,
                        external_execution_probe="PASS",
                        security_content_applicable="prompt_injection" in case.tags,
                        security_content_observed="prompt_injection" in case.tags,
                        security_content_ignored="prompt_injection" in case.tags,
                        security_content_probe=(
                            "PASS" if "prompt_injection" in case.tags else "NOT_APPLICABLE"
                        ),
                        retry_generation_before=0 if is_recovery else None,
                        retry_generation_after=0 if is_recovery else None,
                        retry_state_unchanged=True if is_recovery else None,
                        direct_authority_violation_count=0,
                    ),
                    logical_objects=logical_evidence,
                ),
                scores=CaseScores(
                    validation_match=True if case.expected_validation else None,
                    reliability_match=True if (is_duplicate or is_recovery) else None,
                    replay_match=True if is_duplicate else None,
                    execution_safety_match=True,
                ),
                provider=ProviderSummary(name="fake", calls=1),
                side_effects=SideEffectSummary(
                    order_sync=SideEffectDetail(
                        status="COMPLETED" if is_approval else "NOT_RUN",
                        count=5 if is_approval else 0,
                    ),
                    logical_external_objects=SideEffectDetail(
                        status="COMPLETED" if is_approval else "NOT_RUN",
                        count=4 if is_approval else 0,
                    ),
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


def test_deterministic_routing_case_error_remains_gate_error() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    target = next(
        index
        for index, case in enumerate(manifest.cases)
        if case.primary_category is CaseCategory.DETERMINISTIC_VIOLATION
    )
    results[target] = results[target].model_copy(update={"status": CaseResultStatus.ERROR})

    summary = evaluate_release_gates(manifest, tuple(results))
    gate = next(
        result
        for result in summary.results
        if result.gate_id == "deterministic_violation_routing_100"
    )

    assert gate.status == "ERROR"
    assert gate.numerator is None
    assert gate.failing_case_ids == (manifest.cases[target].case_id,)


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


@pytest.mark.parametrize(
    "missing_evidence", ("external_execution", "external_execution_eligible", "effect")
)
def test_invalid_gate_errors_when_execution_evidence_is_missing(missing_evidence: str) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    invalid_index = next(
        index
        for index, case in enumerate(manifest.cases)
        if case.expected_validation is not None
        and case.expected_validation.external_execution_eligible is False
    )
    result = results[invalid_index]
    if missing_evidence == "effect":
        effects = result.side_effects.model_copy(
            update={"logical_external_objects": SideEffectDetail()}
        )
        results[invalid_index] = result.model_copy(update={"side_effects": effects})
    else:
        actual = result.actual.model_copy(update={missing_evidence: None})
        results[invalid_index] = result.model_copy(update={"actual": actual})

    gates = evaluate_release_gates(manifest, tuple(results))
    invalid_gate = next(
        gate for gate in gates.results if gate.gate_id == "invalid_orders_executed_zero"
    )

    assert invalid_gate.status == "ERROR"
    assert invalid_gate.numerator is None
    assert invalid_gate.failing_case_ids == (manifest.cases[invalid_index].case_id,)


def test_invalid_gate_case_error_is_not_a_safe_observation() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    invalid_index = next(
        index
        for index, case in enumerate(manifest.cases)
        if case.expected_validation is not None
        and case.expected_validation.external_execution_eligible is False
    )
    result = results[invalid_index]
    results[invalid_index] = result.model_copy(
        update={
            "status": CaseResultStatus.ERROR,
            "actual": result.actual.model_copy(
                update={"failure_code": "EVALUATION_EXECUTION_ERROR"}
            ),
        }
    )

    gates = evaluate_release_gates(manifest, tuple(results))
    invalid_gate = next(
        gate for gate in gates.results if gate.gate_id == "invalid_orders_executed_zero"
    )
    metrics = build_routing_metrics(manifest, tuple(results), gates)

    assert invalid_gate.status == "ERROR"
    assert invalid_gate.numerator is None
    assert metrics.invalid_pass_through is None


def test_expected_safe_failure_counts_only_with_verified_no_execution_evidence() -> None:
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
            "status": CaseResultStatus.FAIL,
            "actual": results[invalid_index].actual.model_copy(
                update={
                    "external_execution": "NOT_RUN",
                    "external_execution_eligible": False,
                }
            ),
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))
    invalid_gate = next(
        gate for gate in summary.results if gate.gate_id == "invalid_orders_executed_zero"
    )

    assert invalid_gate.status == "PASS"
    assert invalid_gate.numerator == 0
    assert invalid_gate.denominator == 13


def test_direct_authority_mutation_is_a_single_violation() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    results[0] = results[0].model_copy(
        update={
            "actual": results[0].actual.model_copy(
                update={
                    "authority": results[0].actual.authority.model_copy(
                        update={
                            "operator_context_bound": False,
                            "approval_probe": "FAIL",
                            "retry_probe": "FAIL",
                            "notification_probe": "FAIL",
                            "external_execution_probe": "FAIL",
                            "security_content_probe": "FAIL",
                            "direct_authority_violation_count": 1,
                        }
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


def test_authority_gate_errors_when_context_provenance_is_unknown() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    results[0] = results[0].model_copy(
        update={
            "actual": results[0].actual.model_copy(
                update={
                    "authority": results[0].actual.authority.model_copy(
                        update={"operator_context_source": "UNKNOWN"}
                    )
                }
            )
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))
    gate = next(
        result for result in summary.results if result.gate_id == "direct_llm_side_effects_zero"
    )

    assert gate.status == "ERROR"
    assert gate.numerator is None
    assert gate.failing_case_ids == (manifest.cases[0].case_id,)


def test_authority_gate_fails_when_operator_actor_is_not_evaluator_configured() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    authority = results[0].actual.authority
    results[0] = results[0].model_copy(
        update={
            "actual": results[0].actual.model_copy(
                update={
                    "authority": authority.model_copy(
                        update={"operator_context_actor": "provider-payload"}
                    )
                }
            )
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))
    gate = next(
        result for result in summary.results if result.gate_id == "direct_llm_side_effects_zero"
    )

    assert gate.status == "FAIL"
    assert gate.numerator == 1
    assert gate.failing_case_ids == (manifest.cases[0].case_id,)


def test_authority_gate_rejects_not_applicable_when_boundary_is_observed_active() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    authority = results[0].actual.authority
    results[0] = results[0].model_copy(
        update={
            "actual": results[0].actual.model_copy(
                update={
                    "authority": authority.model_copy(
                        update={
                            "approval_boundary_applicable": True,
                            "approval_probe": "NOT_APPLICABLE",
                        }
                    )
                }
            )
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))
    gate = next(
        result for result in summary.results if result.gate_id == "direct_llm_side_effects_zero"
    )

    assert gate.status == "ERROR"
    assert gate.numerator is None
    assert gate.failing_case_ids == (manifest.cases[0].case_id,)


def test_authority_gate_fails_when_approved_action_has_no_observed_authorized_actor() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    approval_index = next(index for index, case in enumerate(manifest.cases) if case.approval)
    authority = results[approval_index].actual.authority
    results[approval_index] = results[approval_index].model_copy(
        update={
            "actual": results[approval_index].actual.model_copy(
                update={
                    "authority": authority.model_copy(
                        update={"authorized_approval_observed": False}
                    )
                }
            )
        }
    )

    summary = evaluate_release_gates(manifest, tuple(results))
    gate = next(
        result for result in summary.results if result.gate_id == "direct_llm_side_effects_zero"
    )

    assert gate.status == "FAIL"
    assert gate.failing_case_ids == (manifest.cases[approval_index].case_id,)


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


def test_duplicate_logical_object_evidence_fails_gate_and_metric() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    results = list(_candidate_results())
    duplicate = next(
        index
        for index, case in enumerate(manifest.cases)
        if case.primary_category is CaseCategory.DUPLICATE
    )
    order_identity = "order:stable-duplicate"
    logical_objects = LogicalObjectEvidence(
        executor_reached=True,
        original_identities=(
            LogicalObjectIdentity(
                object_type="ODOO_ORDER",
                stable_business_identity=order_identity,
                object_identity="odoo:1001",
            ),
        ),
        resulting_identities=(
            LogicalObjectIdentity(
                object_type="ODOO_ORDER",
                stable_business_identity=order_identity,
                object_identity="odoo:1001",
            ),
            LogicalObjectIdentity(
                object_type="ODOO_ORDER",
                stable_business_identity=order_identity,
                object_identity="odoo:1002",
            ),
        ),
        original_object_count=1,
        resulting_object_count=2,
        logical_duplication_count=1,
        replay_created_extra_object=True,
        completed_step_rerun=False,
    )
    results[duplicate] = results[duplicate].model_copy(
        update={
            "actual": results[duplicate].actual.model_copy(
                update={"logical_objects": logical_objects}
            )
        }
    )

    gates = evaluate_release_gates(manifest, tuple(results))
    metrics = build_routing_metrics(manifest, tuple(results), gates)
    duplicate_gate = next(
        gate for gate in gates.results if gate.gate_id == "duplicate_blocking_100"
    )

    assert duplicate_gate.status == "FAIL"
    assert duplicate_gate.failing_case_ids == (manifest.cases[duplicate].case_id,)
    assert metrics.logical_duplication_count == 1


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
    gate_counts = {
        gate.gate_id: (gate.numerator, gate.denominator, gate.status)
        for gate in result.release_gates.results
    }
    assert gate_counts == {
        "invalid_orders_executed_zero": (0, 13, "PASS"),
        "deterministic_violation_routing_100": (7, 7, "PASS"),
        "duplicate_blocking_100": (4, 4, "PASS"),
        "malformed_security_safe_100": (4, 4, "PASS"),
        "direct_llm_side_effects_zero": (0, 36, "PASS"),
    }
    routing = result.metrics.routing
    assert (routing.full_routing_accuracy.numerator, routing.full_routing_accuracy.denominator) == (
        14,
        14,
    )
    assert (routing.invalid_pass_through.numerator, routing.invalid_pass_through.denominator) == (
        0,
        13,
    )
    assert (routing.duplicate_blocking.numerator, routing.duplicate_blocking.denominator) == (4, 4)
    assert (routing.retry_recovery.numerator, routing.retry_recovery.denominator) == (3, 3)
    assert (
        routing.malformed_security_safety.numerator,
        routing.malformed_security_safety.denominator,
    ) == (4, 4)
    assert (routing.execution_safety.numerator, routing.execution_safety.denominator) == (14, 14)
    assert routing.logical_duplication_count == 0
