from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from opsflow.domain import OrderState
from opsflow.evaluation.corpus import EvaluationBusinessDataProvider, load_catalog, load_manifest
from opsflow.evaluation.doubles import ScriptedProviderFactory
from opsflow.evaluation.models import (
    CaseResultStatus,
    EvaluationMode,
    ExtractionQualityStatus,
)
from opsflow.evaluation.runner import run_case, run_corpus
from opsflow.extraction.provider import StructuredGenerationRequest
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.orchestration.contracts import IntakeExecution, OrchestrationIntakeResult
from opsflow.review.composition import ReviewDateProvider
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
    assert result.actual.intake_execution == "COMPLETED"
    assert result.model_dump(mode="json")["provider"]["name"] == "fake"


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
    asyncio.run(
        run_corpus(_FakeSessionFactory(), manifest, _runtime(), EvaluationMode.PROVIDER_FREE)
    )

    assert constructed is False
