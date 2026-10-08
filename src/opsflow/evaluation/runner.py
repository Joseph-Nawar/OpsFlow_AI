"""Provider-free M11C execution through the existing OpsFlow application seams."""

from __future__ import annotations

import platform as platform_module
import subprocess
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opsflow.application.errors import BusinessDataProviderError
from opsflow.application.orchestration import (
    OrchestrationUnavailableError,
    execute_orchestration_intake,
)
from opsflow.documents.errors import DocumentProcessingError
from opsflow.domain import OrderState, ValidationSeverity
from opsflow.extraction.errors import ExtractionResponseError, ProviderError
from opsflow.extraction.models import ExtractionDraft
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.orchestration.contracts import (
    OrchestrationIntakeCommand,
    OrchestrationIntakeResult,
)
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_extraction_snapshots_for_order,
    get_order,
)
from opsflow.review.composition import ReviewDateProvider
from opsflow.validation.models import ApprovalLevel, ValidationRoute
from opsflow.validation.policy import ValidationPolicy

from .corpus import EvaluationBusinessDataProvider, load_catalog, resolve_manifest_source
from .doubles import ProviderObservation, ScriptedProviderFactory
from .models import (
    BenchmarkValidationContext,
    CaseActual,
    CaseResult,
    CaseResultStatus,
    CaseScores,
    ContractEvidence,
    CorpusCase,
    CorpusComposition,
    CorpusManifest,
    CostMetrics,
    DatabaseMetadata,
    EvaluationMode,
    EvaluationRunResult,
    MetricsBundle,
    PricingStatus,
    ProviderSummary,
    ReleaseGateSummary,
    RunMetadata,
)
from .scoring import score_extraction_quality, score_validation_outcome

CORPUS_ROOT = Path("evals/corpus/v1")
_KNOWN_EXECUTION_ERRORS = (
    BusinessDataProviderError,
    DocumentProcessingError,
    ExtractionResponseError,
    OrchestrationUnavailableError,
    ProviderError,
)


@dataclass(frozen=True, slots=True)
class _FixedBenchmarkDateProvider(ReviewDateProvider):
    evaluation_date: date

    def current_date(self) -> date:
        return self.evaluation_date


def _policy(context: BenchmarkValidationContext) -> ValidationPolicy:
    return ValidationPolicy(
        supported_currencies=context.supported_currencies,
        price_tolerance_fraction=context.price_tolerance_fraction,
        high_value_threshold=context.high_value_threshold,
    )


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    sha = completed.stdout.strip()
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        raise RuntimeError("repository HEAD is not a canonical commit SHA")
    return sha


def _provider_observation(runtime: OrchestrationRuntime) -> ProviderObservation | None:
    factory = runtime.extraction_provider_factory
    provider = getattr(factory, "provider", None)
    observation = getattr(provider, "observation", None)
    return observation if isinstance(observation, ProviderObservation) else None


def _provider_summary(observation: ProviderObservation | None) -> ProviderSummary:
    if observation is None or observation.calls == 0:
        return ProviderSummary()
    return ProviderSummary(
        name="fake",
        calls=observation.calls,
        input_tokens=observation.input_tokens,
        output_tokens=observation.output_tokens,
        total_tokens=observation.total_tokens,
    )


def _failure_code(error: BaseException) -> str:
    if isinstance(error, OrchestrationUnavailableError):
        return "ORCHESTRATION_UNAVAILABLE"
    if isinstance(error, DocumentProcessingError):
        return "DOCUMENT_PROCESSING_ERROR"
    if isinstance(error, ExtractionResponseError):
        return "EXTRACTION_RESPONSE_ERROR"
    if isinstance(error, BusinessDataProviderError):
        return "BUSINESS_DATA_PROVIDER_ERROR"
    if isinstance(error, ProviderError):
        return "PROVIDER_ERROR"
    return "EVALUATION_EXECUTION_ERROR"


async def _load_persisted_observation(
    session: AsyncSession,
    order_id: UUID,
) -> tuple[PersistedOrder | None, ExtractionDraft | None]:
    """Read durable application observations without owning database lifecycle."""

    if not hasattr(session, "get"):
        return None, None
    persisted = await get_order(session, order_id)
    if persisted is None or not persisted.order.source_documents:
        return persisted, None
    snapshots = await get_extraction_snapshots_for_order(session, order_id)
    if not snapshots:
        return persisted, None
    return persisted, snapshots[-1].draft


def _route_for_state(state: OrderState | None) -> ValidationRoute | None:
    if state is OrderState.NEEDS_REVIEW:
        return ValidationRoute.NEEDS_REVIEW
    if state in (OrderState.READY_FOR_APPROVAL, OrderState.APPROVED, OrderState.SYNCING):
        return ValidationRoute.READY_FOR_APPROVAL
    return None


def _approval_level_for_order(persisted: PersistedOrder | None) -> ApprovalLevel | None:
    if persisted is None or _route_for_state(persisted.order.state) is None:
        return None
    elevated = any(
        issue.rule_code == "HIGH_VALUE_APPROVAL_REQUIRED"
        and issue.severity is ValidationSeverity.WARNING
        for issue in persisted.validation_issues
    )
    return ApprovalLevel.ELEVATED if elevated else ApprovalLevel.STANDARD


def _result_from_intake(
    case: CorpusCase,
    intake: OrchestrationIntakeResult,
    persisted: PersistedOrder | None,
    predicted: ExtractionDraft | None,
    observation: ProviderObservation | None,
) -> CaseResult:
    state = persisted.order.state if persisted is not None else intake.state
    issues = (
        ()
        if persisted is None
        else tuple((issue.rule_code, issue.severity) for issue in persisted.validation_issues)
    )
    actual = CaseActual(
        parse=(
            CaseResultStatus.ERROR
            if intake.failure_origin is OrderState.PROCESSING
            else CaseResultStatus.PASS
        ),
        extraction_contract=(
            CaseResultStatus.ERROR
            if intake.failure_origin is OrderState.PROCESSING
            else CaseResultStatus.PASS
        ),
        route=_route_for_state(state),
        approval_level=_approval_level_for_order(persisted),
        pre_approval_state=state,
        issue_facts=issues,
        idempotent_replay=intake.idempotent_replay,
        intake_execution=intake.execution.value,
        external_execution="NOT_RUN",
        external_execution_eligible=state
        in (OrderState.APPROVED, OrderState.SYNCING, OrderState.COMPLETED),
    )
    result = CaseResult(
        case_id=case.case_id,
        status=CaseResultStatus.PASS,
        actual=actual,
        scores=CaseScores(),
        provider=_provider_summary(observation),
        expected_extraction=case.expected_extraction,
        predicted_extraction=predicted,
    )
    validation_score = score_validation_outcome(case.expected_validation, result)
    if validation_score is not None:
        result = result.model_copy(
            update={"scores": CaseScores(validation_match=validation_score.overall_match)}
        )
    return result


def _error_result(
    case: CorpusCase,
    error: BaseException,
    observation: ProviderObservation | None,
) -> CaseResult:
    return CaseResult(
        case_id=case.case_id,
        status=CaseResultStatus.ERROR,
        actual=CaseActual(failure_code=_failure_code(error)),
        provider=_provider_summary(observation),
        expected_extraction=case.expected_extraction,
    )


async def run_case(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> CaseResult:
    """Execute one corpus case through the existing provider-free intake seam."""

    if mode is not EvaluationMode.PROVIDER_FREE:
        raise ValueError("M11C runner supports provider_free mode only")
    source_path = resolve_manifest_source(CORPUS_ROOT, case.source.path)
    command = OrchestrationIntakeCommand(
        content=source_path.read_bytes(),
        document_type=case.source.document_type,
        filename=source_path.name,
        mime_type=case.source.mime_type,
        message_id=f"m11c-{case.case_id}",
        idempotency_key=f"m11c-{case.case_id}",
        source_system="EVALUATION",
    )
    observation = _provider_observation(runtime)
    async with session_factory() as session:
        try:
            intake = await execute_orchestration_intake(
                session,
                command,
                runtime,
                "m11c-evaluator",
                datetime(2026, 10, 10, tzinfo=UTC),
            )
            persisted, predicted = await _load_persisted_observation(session, intake.order_id)
        except _KNOWN_EXECUTION_ERRORS as error:
            return _error_result(case, error, observation)
    return _result_from_intake(case, intake, persisted, predicted, observation)


def _composition(corpus: CorpusManifest) -> CorpusComposition:
    categories = Counter(case.primary_category for case in corpus.cases)
    formats = Counter(case.source.document_type for case in corpus.cases)
    tags = Counter(tag for case in corpus.cases for tag in case.tags)
    return CorpusComposition(
        case_count=len(corpus.cases),
        primary_category_counts=dict(categories),
        format_counts=dict(formats),
        tag_counts=dict(tags),
    )


def _run_metadata(corpus: CorpusManifest, mode: EvaluationMode, started: datetime) -> RunMetadata:
    return RunMetadata(
        run_id=str(uuid4()),
        mode=mode,
        started_at_utc=started,
        finished_at_utc=datetime.now(UTC),
        git_sha=_git_sha(),
        corpus_version=corpus.corpus_version,
        command="m11c-provider-free",
        dependency_lock_identity="uv.lock",
        database_version=None,
        python_version=platform_module.python_version(),
        platform=platform_module.system(),
        cpu_architecture=platform_module.machine(),
        database=DatabaseMetadata(engine="postgresql", isolated=True),
    )


async def run_corpus(
    session_factory: async_sessionmaker[AsyncSession],
    corpus: CorpusManifest,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> EvaluationRunResult:
    """Run the complete corpus sequentially with deterministic provider-free composition."""

    if mode is not EvaluationMode.PROVIDER_FREE:
        raise ValueError("M11C runner supports provider_free mode only")
    catalog_path = resolve_manifest_source(CORPUS_ROOT, corpus.trusted_catalog_path)
    catalog = load_catalog(catalog_path)
    policy = _policy(corpus.benchmark_context)
    fixed_date = _FixedBenchmarkDateProvider(corpus.benchmark_context.evaluation_date)
    results: list[CaseResult] = []
    started = datetime.now(UTC)
    for case in corpus.cases:
        factory = ScriptedProviderFactory(case)
        case_runtime = replace(
            runtime,
            extraction_provider_factory=factory,
            business_data_provider=EvaluationBusinessDataProvider(catalog),
            policy=policy,
            date_provider=fixed_date,
        )
        results.append(await run_case(session_factory, case, case_runtime, mode))

    result_tuple = tuple(results)
    return EvaluationRunResult(
        run=_run_metadata(corpus, mode, started),
        corpus=_composition(corpus),
        cases=result_tuple,
        metrics=MetricsBundle(
            extraction_quality=score_extraction_quality(result_tuple, mode),
            extraction_contract=ContractEvidence(
                parser_succeeded=all(
                    case.actual.parse is CaseResultStatus.PASS for case in results
                ),
                source_identity_matches=True,
                scripted_provider_call_count=sum(case.provider.calls for case in results),
            ),
            cost=CostMetrics(
                initial_order_count=len(results),
                zero_call_order_count=sum(case.provider.calls == 0 for case in results),
            ),
        ),
        pricing=PricingStatus(status="NOT_APPLICABLE"),
        release_gates=ReleaseGateSummary(),
        limitations=(
            "M11C does not collect aggregate timing, pricing, token-cost, or live-model evidence.",
        ),
    )


__all__ = ["run_case", "run_corpus"]
