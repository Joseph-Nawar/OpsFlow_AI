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

from opsflow.domain import OrderState
from opsflow.evaluation.corpus import load_catalog, load_manifest
from opsflow.evaluation.doubles import ScriptedProviderFactory
from opsflow.evaluation.models import EvaluationMode
from opsflow.evaluation.runner import (
    run_approval_sync_scenario,
    run_duplicate_scenario,
    run_recovery_scenario,
)
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.review.composition import ReviewDateProvider
from opsflow.validation.policy import ValidationPolicy


class _FixedDateProvider(ReviewDateProvider):
    def current_date(self) -> date:
        return date(2026, 10, 10)


@pytest.fixture
def isolated_m11c_session_factory() -> Iterator[async_sessionmaker[AsyncSession]]:
    configured_url = os.environ.get("OPSFLOW_M11C_TEST_DATABASE_URL")
    if not configured_url:
        pytest.skip("M11C reliability tests require OPSFLOW_M11C_TEST_DATABASE_URL")
    parsed_url = make_url(configured_url)
    if parsed_url.get_backend_name() != "postgresql":
        pytest.fail("M11C reliability tests require PostgreSQL")
    if parsed_url.database is None or not parsed_url.database.startswith("opsflow_m11c_"):
        pytest.fail("M11C reliability tests require a separately named disposable database")
    engine = create_async_engine(configured_url, poolclass=NullPool)

    asyncio.run(clear_m11c_application_data(engine))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        asyncio.run(engine.dispose())


def _runtime(case) -> OrchestrationRuntime:
    catalog = load_catalog(Path("evals/corpus/v1/trusted-data/catalog.json"))
    return OrchestrationRuntime(
        extraction_provider_factory=ScriptedProviderFactory(case),
        business_data_provider=__import__(
            "opsflow.evaluation.corpus", fromlist=["EvaluationBusinessDataProvider"]
        ).EvaluationBusinessDataProvider(catalog),
        policy=ValidationPolicy(
            supported_currencies=("USD",),
            price_tolerance_fraction=Decimal("0.05"),
            high_value_threshold=Decimal("1000"),
        ),
        date_provider=_FixedDateProvider(),
        review_base_url="https://review.invalid/m11c",
    )


@pytest.mark.parametrize("case_id", ("retry-email-001", "retry-csv-001"))
def test_recovery_scenarios_use_real_retry_authority_and_reach_expected_state(
    isolated_m11c_session_factory, case_id: str
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))

    async def exercise():
        case = next(item for item in manifest.cases if item.case_id == case_id)
        return await run_recovery_scenario(
            isolated_m11c_session_factory,
            case,
            _runtime(case),
            EvaluationMode.PROVIDER_FREE,
        )

    outcome = asyncio.run(exercise())
    assert outcome.failure_state is OrderState.FAILED_RETRYABLE
    expected_origin = (
        OrderState.PROCESSING if case_id == "retry-email-001" else OrderState.EXTRACTED
    )
    assert outcome.failure_origin is expected_origin
    assert outcome.final_state is OrderState.READY_FOR_APPROVAL
    assert outcome.retry_used


def test_duplicate_scenarios_use_real_idempotency_without_new_graph(
    isolated_m11c_session_factory,
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))

    async def exercise():
        outcomes = []
        for case in manifest.cases:
            if case.replay is not None:
                outcomes.append(
                    await run_duplicate_scenario(
                        isolated_m11c_session_factory,
                        case,
                        _runtime(case),
                        EvaluationMode.PROVIDER_FREE,
                    )
                )
        return outcomes

    outcomes = asyncio.run(exercise())
    assert len(outcomes) == 4
    assert all(item.authoritative_order_count == 1 for item in outcomes)
    assert all(item.idempotent_replay for item in outcomes)
    assert all(item.logical_external_object_count == 0 for item in outcomes)
    assert all(item.case_result.scores.replay_match is True for item in outcomes)
    assert all(item.case_result.actual.replay is not None for item in outcomes)
    assert all(
        item.case_result.actual.replay.creation_disposition.value == "REPLAYED_EXISTING"
        and item.case_result.actual.replay.intake_execution.value == "STANDING_DOWN"
        and item.case_result.actual.replay.seed_order_id
        == item.case_result.actual.replay.replay_order_id
        and item.case_result.actual.replay.provider_work_stood_down
        for item in outcomes
    )


def test_approved_sync_recovery_uses_real_review_and_phase9_receipts(
    isolated_m11c_session_factory,
) -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(item for item in manifest.cases if item.case_id == "retry-csv-002")

    outcome = asyncio.run(
        run_approval_sync_scenario(
            isolated_m11c_session_factory,
            case,
            _runtime(case),
            EvaluationMode.PROVIDER_FREE,
        )
    )

    assert outcome.approved_state is OrderState.APPROVED
    assert outcome.failure_state is OrderState.FAILED_RETRYABLE
    assert outcome.final_state is OrderState.COMPLETED
    assert outcome.retry_generation == 1
    assert outcome.prior_receipt_preserved
    assert outcome.resumed_steps
    assert "ODOO_LOOKUP" not in outcome.resumed_steps
    assert "ODOO_BRIDGE" not in outcome.resumed_steps
    assert outcome.logical_external_object_count == 4
    assert outcome.case_result.actual.pre_approval_state is OrderState.READY_FOR_APPROVAL
    assert outcome.case_result.status.value == "PASS"
    assert outcome.case_result.scores.validation_match is True
    assert outcome.case_result.scores.execution_safety_match is True
    assert outcome.case_result.actual.recovery is not None
    assert outcome.case_result.actual.recovery.final_state is OrderState.COMPLETED
    assert outcome.case_result.actual.recovery.prior_receipts_preserved is True


def test_reliability_outputs_are_provider_free_and_no_live_provider_is_used(
    isolated_m11c_session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import opsflow.orchestration.composition as composition

    monkeypatch.setattr(
        composition,
        "GeminiProvider",
        lambda *_args, **_kwargs: pytest.fail("reliability evaluation must not construct Gemini"),
    )
    manifest = load_manifest(Path("evals/corpus/v1"))
    case = next(item for item in manifest.cases if item.case_id == "retry-csv-002")

    outcome = asyncio.run(
        run_approval_sync_scenario(
            isolated_m11c_session_factory,
            case,
            _runtime(case),
            EvaluationMode.PROVIDER_FREE,
        )
    )

    assert outcome.case_result.provider.name == "fake"
    assert outcome.case_result.provider.calls > 0
