from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from db_support import clear_m11c_application_data
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import opsflow.evaluation.runner as runner_module
from opsflow.domain import OrderState
from opsflow.evaluation.corpus import EvaluationBusinessDataProvider, load_catalog, load_manifest
from opsflow.evaluation.doubles import ScriptedProviderFactory
from opsflow.evaluation.models import (
    CaseResult,
    CaseResultStatus,
    EvaluationMode,
    ExtractionQualityStatus,
)
from opsflow.evaluation.runner import ReliabilityEvidence, run_case, run_corpus
from opsflow.extraction.provider import StructuredGenerationRequest
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.orchestration.contracts import IntakeExecution, OrchestrationIntakeResult
from opsflow.persistence.models import SourceDocumentModel
from opsflow.persistence.repositories import get_audit_events, get_extraction_snapshot, get_order
from opsflow.review.composition import ReviewDateProvider
from opsflow.validation.models import ApprovalLevel
from opsflow.validation.policy import ValidationPolicy


class _FixedDateProvider(ReviewDateProvider):
    def current_date(self) -> date:
        return date(2026, 10, 10)


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeSessionFactory:
    def __call__(self) -> _FakeSession:
        return _FakeSession()


def _runtime(factory=None) -> OrchestrationRuntime:
    catalog = load_catalog(Path("evals/corpus/v1/trusted-data/catalog.json"))
    return OrchestrationRuntime(
        extraction_provider_factory=factory or (lambda: None),
        business_data_provider=EvaluationBusinessDataProvider(catalog),
        policy=ValidationPolicy(
            supported_currencies=("USD",),
            price_tolerance_fraction=Decimal("0.05"),
            high_value_threshold=Decimal("1000"),
        ),
        date_provider=_FixedDateProvider(),
        review_base_url="https://review.invalid/evaluation",
    )


class _RecordingBusinessDataProvider:
    def __init__(self, delegate: EvaluationBusinessDataProvider) -> None:
        self.delegate = delegate
        self.requests = []

    async def get_validation_data(self, request):
        self.requests.append(request)
        return await self.delegate.get_validation_data(request)


@pytest.fixture
def m11c_session_factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    configured_url = os.environ.get("OPSFLOW_M11C_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("M11C real-path tests require OPSFLOW_M11C_TEST_DATABASE_URL")
    parsed_url = make_url(configured_url)
    if parsed_url.get_backend_name() != "postgresql":
        pytest.fail("M11C real-path tests require a PostgreSQL database")
    if parsed_url.database is None or not parsed_url.database.startswith("opsflow_m11c_"):
        pytest.fail("M11C real-path tests require a separately named disposable database")
    engine = create_async_engine(configured_url, poolclass=NullPool)
    asyncio.run(clear_m11c_application_data(engine))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


async def _source_order_observation(
    session_factory: async_sessionmaker[AsyncSession],
    case,
):
    async with session_factory() as session:
        source = await session.scalar(
            select(SourceDocumentModel).where(SourceDocumentModel.sha256 == case.source.sha256)
        )
        assert source is not None
        persisted = await get_order(session, source.order_id)
        snapshot = await get_extraction_snapshot(session, source.order_id, source.id)
        audits = await get_audit_events(session, source.order_id)
    return persisted, snapshot, audits


def _real_case_runtime(case, business_data_provider=None) -> OrchestrationRuntime:
    runtime = _runtime(ScriptedProviderFactory(case))
    return OrchestrationRuntime(
        extraction_provider_factory=runtime.extraction_provider_factory,
        business_data_provider=business_data_provider or runtime.business_data_provider,
        policy=runtime.policy,
        date_provider=runtime.date_provider,
        review_base_url=runtime.review_base_url,
    )


def test_real_postgresql_path_persists_ready_order_and_request_driven_lookup(
    m11c_session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import opsflow.orchestration.composition as composition

    monkeypatch.setattr(
        composition,
        "GeminiProvider",
        lambda *_args, **_kwargs: pytest.fail("real provider-free path must not construct Gemini"),
    )
    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(item for item in manifest.cases if item.case_id == "retry-email-001")
    catalog = load_catalog(Path("evals/corpus/v1/trusted-data/catalog.json"))
    provider = _RecordingBusinessDataProvider(EvaluationBusinessDataProvider(catalog))
    runtime = _real_case_runtime(case, provider)

    async def exercise():
        result = await run_case(
            m11c_session_factory,
            case,
            runtime,
            EvaluationMode.PROVIDER_FREE,
        )
        persisted, snapshot, audits = await _source_order_observation(m11c_session_factory, case)
        return result, persisted, snapshot, audits

    result, persisted, snapshot, audits = asyncio.run(exercise())

    assert persisted is not None
    assert snapshot is not None
    assert result.status is CaseResultStatus.PASS
    assert result.actual.route == case.expected_validation.route
    assert result.actual.pre_approval_state is OrderState.READY_FOR_APPROVAL
    assert result.provider.name == "fake"
    assert result.provider.calls == 1
    assert provider.requests
    request = provider.requests[0]
    assert request.customer_reference == snapshot.draft.customer_reference
    assert request.skus == tuple(line.sku for line in snapshot.draft.lines)
    assert persisted.order.state is OrderState.READY_FOR_APPROVAL
    assert audits[-1].event_type == "ORDER_READY_FOR_APPROVAL"
    assert result.model_dump(mode="json")["provider"]["name"] == "fake"


def test_real_postgresql_path_persists_deterministic_violation_truth(
    m11c_session_factory,
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(item for item in manifest.cases if item.case_id == "deterministic-csv-001")
    runtime = _real_case_runtime(case)

    async def exercise():
        result = await run_case(
            m11c_session_factory,
            case,
            runtime,
            EvaluationMode.PROVIDER_FREE,
        )
        persisted, snapshot, _audits = await _source_order_observation(m11c_session_factory, case)
        return result, persisted, snapshot

    result, persisted, snapshot = asyncio.run(exercise())

    assert persisted is not None
    assert snapshot is not None
    assert result.actual.route is case.expected_validation.route
    assert result.actual.approval_level is ApprovalLevel.STANDARD
    assert result.actual.pre_approval_state is OrderState.NEEDS_REVIEW
    assert tuple(
        (issue.rule_code, issue.severity) for issue in persisted.validation_issues
    ) == tuple(
        (code, case.expected_validation.issue_severities[code])
        for code in case.expected_validation.issue_codes
    )
    assert persisted.order.state is OrderState.NEEDS_REVIEW


def test_real_postgresql_path_records_bounded_processing_failure(
    m11c_session_factory,
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(item for item in manifest.cases if item.case_id == "security-email-001")
    runtime = _real_case_runtime(case)

    async def exercise():
        result = await run_case(
            m11c_session_factory,
            case,
            runtime,
            EvaluationMode.PROVIDER_FREE,
        )
        return result, *(await _source_order_observation(m11c_session_factory, case))

    result, persisted, snapshot, audits = asyncio.run(exercise())

    assert persisted is not None
    assert snapshot is None
    assert result.actual.parse is CaseResultStatus.ERROR
    assert result.actual.extraction_contract is CaseResultStatus.ERROR
    assert result.actual.external_execution_eligible is False
    assert persisted.order.state is OrderState.FAILED_FINAL
    assert persisted.order.failure_origin is OrderState.PROCESSING
    assert audits[-1].event_type == "ORDER_PROCESSING_FAILED"


def test_real_postgresql_security_source_cannot_authorize_side_effects(
    m11c_session_factory,
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(item for item in manifest.cases if item.case_id == "security-csv-001")
    runtime = _real_case_runtime(case)

    async def exercise():
        result = await run_case(
            m11c_session_factory,
            case,
            runtime,
            EvaluationMode.PROVIDER_FREE,
        )
        return result, *(await _source_order_observation(m11c_session_factory, case))

    result, persisted, _snapshot, _audits = asyncio.run(exercise())

    assert persisted is not None
    assert result.actual.external_execution == "NOT_RUN"
    assert result.actual.external_execution_eligible is False
    assert result.actual.route is not None
    assert result.actual.approval_level is ApprovalLevel.STANDARD
    assert result.actual.pre_approval_state is not OrderState.APPROVED


def test_run_case_uses_the_orchestration_intake_seam_and_serializes_actuals(monkeypatch) -> None:
    import opsflow.evaluation.runner as runner

    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(case for case in manifest.cases if case.case_id == "normal-email-001")
    captured: dict[str, Any] = {}
    factory = ScriptedProviderFactory(case)

    async def fake_intake(session, command, runtime, actor, recorded_at):
        provider = runtime.extraction_provider_factory()
        await provider.generate_structured(
            StructuredGenerationRequest(
                prompt_version="test",
                system_instruction="test",
                user_content="test",
                response_schema={},
            )
        )
        captured.update(
            command=command,
            runtime=runtime,
            actor=actor,
            recorded_at=recorded_at,
            session=session,
        )
        return OrchestrationIntakeResult(
            order_id=uuid4(),
            state=OrderState.NEEDS_REVIEW,
            failure_origin=None,
            idempotent_replay=False,
            execution=IntakeExecution.COMPLETED,
        )

    monkeypatch.setattr(runner, "execute_orchestration_intake", fake_intake)

    result = asyncio.run(
        run_case(_FakeSessionFactory(), case, _runtime(factory), EvaluationMode.PROVIDER_FREE)
    )

    assert captured["command"].document_type is case.source.document_type
    assert captured["command"].mime_type == case.source.mime_type
    assert captured["command"].idempotency_key == "m11c-normal-email-001"
    assert captured["actor"] == "m11c-evaluator"
    assert result.status is CaseResultStatus.PASS
    assert result.actual.pre_approval_state is OrderState.NEEDS_REVIEW
    assert result.actual.intake_execution is IntakeExecution.COMPLETED
    assert result.model_dump(mode="json")["provider"]["name"] == "fake"


def test_run_case_rejects_unknown_provider_factory_before_invocation(monkeypatch) -> None:
    import opsflow.evaluation.runner as runner

    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(item for item in manifest.cases if item.case_id == "normal-email-001")
    factory_calls = 0
    intake_calls = 0

    def forbidden_factory() -> object:
        nonlocal factory_calls
        factory_calls += 1
        return object()

    async def fake_intake(_session, _command, supplied_runtime, *_args):
        nonlocal intake_calls
        intake_calls += 1
        supplied_runtime.extraction_provider_factory()
        return OrchestrationIntakeResult(
            order_id=uuid4(),
            state=OrderState.NEEDS_REVIEW,
            failure_origin=None,
            idempotent_replay=False,
            execution=IntakeExecution.COMPLETED,
        )

    async def no_persisted_observation(_session, _order_id):
        return None, None

    monkeypatch.setattr(runner, "execute_orchestration_intake", fake_intake)
    monkeypatch.setattr(runner, "_load_persisted_observation", no_persisted_observation)

    result = asyncio.run(
        run_case(
            _FakeSessionFactory(),
            case,
            _runtime(forbidden_factory),
            EvaluationMode.PROVIDER_FREE,
        )
    )

    assert result.status is CaseResultStatus.ERROR
    assert intake_calls == 0
    assert factory_calls == 0


def test_run_corpus_is_provider_free_and_accounts_for_all_manifest_cases(monkeypatch) -> None:
    import opsflow.evaluation.runner as runner

    manifest = load_manifest(Path("evals/corpus/v1"))
    calls = 0

    async def fake_intake(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return OrchestrationIntakeResult(
            order_id=uuid4(),
            state=OrderState.NEEDS_REVIEW,
            failure_origin=None,
            idempotent_replay=False,
            execution=IntakeExecution.COMPLETED,
        )

    monkeypatch.setattr(runner, "execute_orchestration_intake", fake_intake)

    async def fake_reliability(session_factory, case, runtime, mode):
        return ReliabilityEvidence(
            case_result=await run_case(session_factory, case, runtime, mode),
            order_id=uuid4(),
            failure_state=None,
            failure_origin=None,
            final_state=OrderState.NEEDS_REVIEW,
        )

    monkeypatch.setattr(runner, "run_recovery_scenario", fake_reliability)
    monkeypatch.setattr(runner, "run_duplicate_scenario", fake_reliability)
    monkeypatch.setattr(runner, "run_approval_sync_scenario", fake_reliability)

    result = asyncio.run(
        run_corpus(_FakeSessionFactory(), manifest, _runtime(), EvaluationMode.PROVIDER_FREE)
    )

    assert calls == 36
    assert len(result.cases) == 36
    assert result.metrics.extraction_quality.status is ExtractionQualityStatus.NOT_APPLICABLE
    assert result.metrics.extraction_quality.complete_exact_match is None
    assert result.metrics.extraction_quality.field_micro_f1 is None
    assert result.run.command == "m11c-provider-free"
    assert "expected_extraction" not in result.model_dump(mode="json")["cases"][0]


def test_provider_free_runner_does_not_construct_a_live_gemini_provider(monkeypatch) -> None:
    import opsflow.evaluation.runner as runner

    manifest = load_manifest(Path("evals/corpus/v1"))
    constructed = False

    def live_constructor():
        nonlocal constructed
        constructed = True
        raise AssertionError("live Gemini must not be constructed")

    monkeypatch.setattr(runner, "GeminiProvider", live_constructor, raising=False)

    async def fake_intake(*_args, **_kwargs):
        return OrchestrationIntakeResult(
            order_id=uuid4(),
            state=OrderState.NEEDS_REVIEW,
            failure_origin=None,
            idempotent_replay=False,
            execution=IntakeExecution.COMPLETED,
        )

    monkeypatch.setattr(runner, "execute_orchestration_intake", fake_intake)

    async def fake_reliability(session_factory, case, runtime, mode):
        return ReliabilityEvidence(
            case_result=await run_case(session_factory, case, runtime, mode),
            order_id=uuid4(),
            failure_state=None,
            failure_origin=None,
            final_state=OrderState.NEEDS_REVIEW,
        )

    monkeypatch.setattr(runner, "run_recovery_scenario", fake_reliability)
    monkeypatch.setattr(runner, "run_duplicate_scenario", fake_reliability)
    monkeypatch.setattr(runner, "run_approval_sync_scenario", fake_reliability)
    asyncio.run(
        run_corpus(_FakeSessionFactory(), manifest, _runtime(), EvaluationMode.PROVIDER_FREE)
    )

    assert constructed is False


def test_m11c_runner_has_no_evaluation_session_policy_substitution() -> None:
    import opsflow.evaluation.runner as runner

    assert not hasattr(runner, "_execution_session_factory")


def test_provider_free_runner_has_fail_closed_remote_adapter_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    import opsflow.evaluation.runner as runner

    def forbidden_http_client(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("provider-free evaluation must not construct external HTTP clients")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_http_client)
    monkeypatch.setattr(runner, "GeminiProvider", forbidden_http_client, raising=False)

    manifest = load_manifest(Path("evals/corpus/v1"))

    async def fake_intake(*_args: object, **_kwargs: object) -> OrchestrationIntakeResult:
        return OrchestrationIntakeResult(
            order_id=uuid4(),
            state=OrderState.NEEDS_REVIEW,
            failure_origin=None,
            idempotent_replay=False,
            execution=IntakeExecution.COMPLETED,
        )

    monkeypatch.setattr(runner, "execute_orchestration_intake", fake_intake)

    async def fake_reliability(session_factory, case, runtime, mode):
        return ReliabilityEvidence(
            case_result=await run_case(session_factory, case, runtime, mode),
            order_id=uuid4(),
            failure_state=None,
            failure_origin=None,
            final_state=OrderState.NEEDS_REVIEW,
        )

    monkeypatch.setattr(runner, "run_recovery_scenario", fake_reliability)
    monkeypatch.setattr(runner, "run_duplicate_scenario", fake_reliability)
    monkeypatch.setattr(runner, "run_approval_sync_scenario", fake_reliability)

    result = asyncio.run(
        run_corpus(_FakeSessionFactory(), manifest, _runtime(), EvaluationMode.PROVIDER_FREE)
    )

    assert len(result.cases) == 36


def test_run_corpus_keeps_benchmark_mismatch_as_structured_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    duplicate_case = next(case for case in manifest.cases if case.replay is not None)

    def result_for(case, status: CaseResultStatus) -> CaseResult:
        return CaseResult(case_id=case.case_id, status=status)

    async def fake_case(_session_factory, case, _runtime, _mode):
        return result_for(case, CaseResultStatus.PASS)

    async def fake_duplicate(_session_factory, case, _runtime, _mode):
        return ReliabilityEvidence(
            case_result=result_for(
                case,
                CaseResultStatus.FAIL
                if case.case_id == duplicate_case.case_id
                else CaseResultStatus.PASS,
            ),
            order_id=uuid4(),
            failure_state=None,
            failure_origin=None,
            final_state=None,
        )

    async def fake_recovery(_session_factory, case, _runtime, _mode):
        return ReliabilityEvidence(
            case_result=result_for(case, CaseResultStatus.PASS),
            order_id=uuid4(),
            failure_state=None,
            failure_origin=None,
            final_state=None,
        )

    monkeypatch.setattr(runner_module, "run_case", fake_case)
    monkeypatch.setattr(runner_module, "run_duplicate_scenario", fake_duplicate)
    monkeypatch.setattr(runner_module, "run_recovery_scenario", fake_recovery)
    monkeypatch.setattr(runner_module, "run_approval_sync_scenario", fake_recovery)

    result = asyncio.run(
        run_corpus(_FakeSessionFactory(), manifest, _runtime(), EvaluationMode.PROVIDER_FREE)
    )

    observed = next(case for case in result.cases if case.case_id == duplicate_case.case_id)
    assert observed.status is CaseResultStatus.FAIL
    duplicate_gate = next(
        gate for gate in result.release_gates.results if gate.gate_id == "duplicate_blocking_100"
    )
    assert duplicate_gate.status == "FAIL"
    assert duplicate_case.case_id in duplicate_gate.failing_case_ids
