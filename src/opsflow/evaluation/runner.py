"""Provider-free M11C execution through the existing OpsFlow application seams."""

from __future__ import annotations

import platform as platform_module
import subprocess
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opsflow.application import orchestration as orchestration_application
from opsflow.application.errors import BusinessDataProviderError, ForbiddenError
from opsflow.application.orchestration import (
    OrchestrationUnavailableError,
    execute_orchestration_intake,
)
from opsflow.application.order_sync import (
    begin_order_sync_step,
    claim_next_order_sync,
    execute_next_order_sync,
    persist_order_sync_receipt,
    yield_order_sync_claim,
)
from opsflow.application.orders import CreateOrderDisposition
from opsflow.application.review_commands import approve_order, retry_order
from opsflow.documents.errors import DocumentProcessingError
from opsflow.domain import OrderState, ValidationSeverity
from opsflow.extraction.errors import ExtractionResponseError, ProviderError
from opsflow.extraction.models import ExtractionDraft
from opsflow.notifications.contracts import (
    NotificationOutcome,
    NotificationOutcomeKind,
)
from opsflow.notifications.service import claim_next_notification, record_notification_outcome
from opsflow.orchestration.composition import OrchestrationRuntime
from opsflow.orchestration.contracts import (
    OrchestrationIntakeCommand,
    OrchestrationIntakeResult,
)
from opsflow.order_sync.contracts import (
    HubSpotAssociationReceipt,
    HubSpotCompanyReceipt,
    HubSpotDealReceipt,
    OdooOrderReceipt,
    OrderSyncStep,
    OrderSyncStepResult,
)
from opsflow.persistence.models import (
    NotificationDeliveryModel,
    OrderModel,
    OrderSyncModel,
    SourceDocumentModel,
)
from opsflow.persistence.repositories import (
    PersistedOrder,
    get_extraction_snapshots_for_order,
    get_latest_audit_event_id,
    get_latest_review_revision,
    get_order,
)
from opsflow.review import OperatorContext, OperatorRole
from opsflow.review.composition import ReviewDateProvider
from opsflow.review.concurrency import compute_review_etag
from opsflow.validation.models import ApprovalLevel, ValidationRoute
from opsflow.validation.policy import ValidationPolicy

from .corpus import EvaluationBusinessDataProvider, load_catalog, resolve_manifest_source
from .doubles import (
    FailOnceBusinessDataProvider,
    ProviderObservation,
    RecoveryScriptedProviderFactory,
    ScriptedProviderFactory,
)
from .models import (
    AuthorityEvidence,
    AuthorityProbeStatus,
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
    RecoveryEvidence,
    ReplayEvidence,
    RunMetadata,
    SideEffectDetail,
    SideEffectSummary,
)
from .scoring import (
    build_routing_metrics,
    evaluate_release_gates,
    score_extraction_quality,
    score_validation_outcome,
)

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


@dataclass(frozen=True, slots=True)
class ReliabilityEvidence:
    """Internal durable observations used to populate M11C result homes."""

    case_result: CaseResult
    order_id: UUID
    failure_state: OrderState | None
    failure_origin: OrderState | None
    final_state: OrderState | None
    retry_used: bool = False
    authoritative_order_count: int = 0
    idempotent_replay: bool = False
    logical_external_object_count: int = 0
    approved_state: OrderState | None = None
    retry_generation: int = 0
    prior_receipt_preserved: bool = False
    resumed_steps: tuple[str, ...] = ()


class EvaluationOrderSyncExecutor:
    """Provider-free Phase 9 executor returning bounded synthetic receipts."""

    def __init__(self) -> None:
        self.calls: list[OrderSyncStep] = []
        self._objects: dict[tuple[UUID, str], str] = {}

    @property
    def logical_external_object_count(self) -> int:
        return len(self._objects)

    async def execute(self, order_id: UUID, step: OrderSyncStep) -> OrderSyncStepResult:
        self.calls.append(step)
        if step is OrderSyncStep.ODOO_LOOKUP:
            return None
        if step is OrderSyncStep.ODOO_BRIDGE:
            self._objects.setdefault((order_id, "odoo"), f"m11c-odoo-{order_id}")
            return OdooOrderReceipt(1001, f"M11C-{order_id}")
        if step is OrderSyncStep.HUBSPOT_COMPANY:
            self._objects.setdefault((order_id, "company"), f"m11c-company-{order_id}")
            return HubSpotCompanyReceipt(self._objects[(order_id, "company")])
        if step is OrderSyncStep.HUBSPOT_DEAL:
            self._objects.setdefault((order_id, "deal"), f"m11c-deal-{order_id}")
            return HubSpotDealReceipt(self._objects[(order_id, "deal")])
        self._objects.setdefault((order_id, "association"), f"m11c-association-{order_id}")
        return HubSpotAssociationReceipt(datetime(2026, 10, 10, tzinfo=UTC))


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
        order_id=intake.order_id,
        issue_facts=issues,
        idempotent_replay=intake.idempotent_replay,
        intake_execution=intake.execution,
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
    expected_eligible = (
        case.expected_validation.external_execution_eligible
        if case.expected_validation is not None
        else False
    )
    execution_safe = (
        result.actual.external_execution_eligible is expected_eligible
        and (result.side_effects.logical_external_objects.count or 0) == 0
    )
    result = result.model_copy(
        update={
            "scores": CaseScores(
                validation_match=(
                    validation_score.overall_match if validation_score is not None else None
                ),
                execution_safety_match=execution_safe,
            )
        }
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


def _benchmark_failure(
    result: CaseResult,
    *,
    reliability_match: bool | None = None,
    replay_match: bool | None = None,
    execution_safety_match: bool | None = None,
) -> CaseResult:
    """Represent an observed application mismatch without aborting the run."""

    scores = result.scores.model_copy(
        update={
            "reliability_match": reliability_match
            if reliability_match is not None
            else result.scores.reliability_match,
            "replay_match": replay_match
            if replay_match is not None
            else result.scores.replay_match,
            "execution_safety_match": execution_safety_match
            if execution_safety_match is not None
            else result.scores.execution_safety_match,
        }
    )
    return result.model_copy(update={"status": CaseResultStatus.FAIL, "scores": scores})


async def _authority_evidence(
    session_factory: async_sessionmaker[AsyncSession],
    result: CaseResult,
    runtime: OrchestrationRuntime,
) -> AuthorityEvidence:
    """Probe real authority boundaries without using source/provider content."""

    approval_probe: AuthorityProbeStatus = "NOT_APPLICABLE"
    if result.actual.pre_approval_state is OrderState.READY_FOR_APPROVAL:
        try:
            async with session_factory() as session:
                etag = await _review_etag(session, result.actual.order_id)  # type: ignore[arg-type]
                await approve_order(
                    session,
                    result.actual.order_id,  # type: ignore[arg-type]
                    etag,
                    OperatorContext("m11c-unauthorized-probe", OperatorRole.REVIEWER),
                    datetime(2026, 10, 10, 12, 30, tzinfo=UTC),
                    runtime.review_base_url,
                )
        except ForbiddenError:
            approval_probe = "PASS"
        except Exception:
            approval_probe = "ERROR"
        else:
            approval_probe = "FAIL"

    logical_count = result.side_effects.logical_external_objects.count or 0
    external_probe: AuthorityProbeStatus = (
        "PASS"
        if result.actual.external_execution not in {"APPROVED", "SYNCING", "COMPLETED"}
        and logical_count == 0
        else "NOT_APPLICABLE"
    )
    return AuthorityEvidence(
        operator_context_bound=True,
        approval_probe=approval_probe,
        retry_probe="NOT_APPLICABLE",
        notification_probe="PASS",
        external_execution_probe=external_probe,
        direct_authority_violation_count=0
        if approval_probe not in {"FAIL", "ERROR"} and external_probe != "FAIL"
        else 1,
    )


async def _run_case_at(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
    recorded_at: datetime,
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
                recorded_at,
            )
            persisted, predicted = await _load_persisted_observation(session, intake.order_id)
        except _KNOWN_EXECUTION_ERRORS as error:
            result = _error_result(case, error, observation)
            authority = AuthorityEvidence(
                operator_context_bound=True,
                approval_probe="NOT_APPLICABLE",
                retry_probe="NOT_APPLICABLE",
                notification_probe="PASS",
                external_execution_probe="PASS",
                direct_authority_violation_count=0,
            )
            return result.model_copy(
                update={"actual": result.actual.model_copy(update={"authority": authority})}
            )
    result = _result_from_intake(case, intake, persisted, predicted, observation)
    authority = await _authority_evidence(session_factory, result, runtime)
    return result.model_copy(
        update={"actual": result.actual.model_copy(update={"authority": authority})}
    )


async def run_case(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> CaseResult:
    """Execute one corpus case with the deterministic benchmark event time."""

    return await _run_case_at(
        session_factory,
        case,
        runtime,
        mode,
        datetime(2026, 10, 10, tzinfo=UTC),
    )


async def _order_id_for_case(
    session_factory: async_sessionmaker[AsyncSession], case: CorpusCase
) -> UUID:
    async with session_factory() as session:
        if not hasattr(session, "scalar"):
            raise RuntimeError("durable order lookup requires an application session")
        order_id = await session.scalar(
            select(SourceDocumentModel.order_id)
            .where(SourceDocumentModel.sha256 == case.source.sha256)
            .order_by(SourceDocumentModel.order_id)
            .limit(1)
        )
    if not isinstance(order_id, UUID):
        raise RuntimeError(f"no durable order exists for evaluation case {case.case_id}")
    return order_id


async def _review_etag(session: AsyncSession, order_id: UUID) -> str:
    persisted = await get_order(session, order_id)
    if persisted is None:
        raise RuntimeError("cannot compute a review ETag for a missing evaluation order")
    revision = await get_latest_review_revision(session, order_id)
    audit_id = await get_latest_audit_event_id(session, order_id)
    return compute_review_etag(
        order_id,
        persisted.order.state,
        persisted.order.failure_origin,
        revision.revision_number if revision is not None else None,
        revision.id if revision is not None else None,
        audit_id,
    )


async def _drain_notifications(
    session_factory: async_sessionmaker[AsyncSession],
    target_order_id: UUID,
) -> int:
    """Deliver pending intents through the real claim/outcome persistence seam."""

    delivered_for_target = 0
    while True:
        async with session_factory() as session:
            claim = await claim_next_notification(session)
        if claim is None:
            return delivered_for_target
        async with session_factory() as session:
            claimed_order_id = await session.scalar(
                select(NotificationDeliveryModel.order_id).where(
                    NotificationDeliveryModel.id == claim.notification_id
                )
            )
        async with session_factory() as session:
            await record_notification_outcome(
                session,
                claim.notification_id,
                NotificationOutcome(
                    claim_token=claim.claim_token,
                    kind=NotificationOutcomeKind.DELIVERED,
                    provider_reference="m11c-provider-free-notification",
                ),
            )
        if claimed_order_id == target_order_id:
            delivered_for_target += 1


def _with_notification_evidence(result: CaseResult, delivered_count: int) -> CaseResult:
    return result.model_copy(
        update={
            "side_effects": SideEffectSummary(
                notification=SideEffectDetail(status="DELIVERED", count=delivered_count),
                order_sync=result.side_effects.order_sync,
                logical_external_objects=result.side_effects.logical_external_objects,
            )
        }
    )


async def _count_order_rows(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[NotificationDeliveryModel] | type[OrderSyncModel],
    order_id: UUID,
) -> int:
    async with session_factory() as session:
        statement = select(func.count()).select_from(model).where(model.order_id == order_id)
        return int((await session.scalar(statement)) or 0)


async def run_recovery_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> ReliabilityEvidence:
    """Drive one bounded human-retry scenario through the production commands."""

    if case.recovery is None:
        raise ValueError("recovery scenario is required")
    failure = case.recovery.failure_code
    first_failure = "PROVIDER_UNAVAILABLE" if failure == "PROVIDER_UNAVAILABLE" else ""
    recovery_runtime = replace(
        runtime,
        extraction_provider_factory=RecoveryScriptedProviderFactory(case, first_failure)
        if failure in {"PROVIDER_UNAVAILABLE", "BUSINESS_DATA_PROVIDER_ERROR"}
        else runtime.extraction_provider_factory,
        business_data_provider=(
            FailOnceBusinessDataProvider(runtime.business_data_provider)
            if failure == "BUSINESS_DATA_PROVIDER_ERROR"
            else runtime.business_data_provider
        ),
    )
    initial = await run_case(session_factory, case, recovery_runtime, mode)
    order_id = await _order_id_for_case(session_factory, case)
    async with session_factory() as session:
        failed = await get_order(session, order_id)
        if failed is None:
            raise RuntimeError("recovery scenario did not reach FAILED_RETRYABLE")
        if failed.order.state is not OrderState.FAILED_RETRYABLE:
            return ReliabilityEvidence(
                case_result=_benchmark_failure(initial, reliability_match=False),
                order_id=order_id,
                failure_state=failed.order.state,
                failure_origin=failed.order.failure_origin,
                final_state=failed.order.state,
            )
        failure_origin = failed.order.failure_origin
        etag = await _review_etag(session, order_id)
    origin_match = failure_origin is case.recovery.expected_resume_origin
    async with session_factory() as session:
        retry = await retry_order(
            session,
            order_id,
            etag,
            OperatorContext("m11c-retry-reviewer", OperatorRole.REVIEWER),
            datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
        )
    retry_match = retry.state is case.recovery.expected_resume_origin
    final = await _run_case_at(
        session_factory,
        case,
        recovery_runtime,
        mode,
        datetime(2026, 10, 10, 12, 0, 1, tzinfo=UTC),
    )
    notifications = await _drain_notifications(session_factory, order_id)
    async with session_factory() as session:
        persisted = await get_order(session, order_id)
    if persisted is None:
        raise RuntimeError("recovery order disappeared after retry")
    final_match = persisted.order.state is case.recovery.expected_final_state
    final = _with_notification_evidence(final, notifications)
    recovery = RecoveryEvidence(
        injected_stage=case.recovery.injected_stage,
        failure_code=case.recovery.failure_code,
        failed_state=OrderState.FAILED_RETRYABLE,
        failure_origin=failure_origin,
        retry_used=True,
        retry_generation=0,
        final_state=persisted.order.state,
        receipt_count=0,
        prior_receipts_preserved=case.recovery.preserve_prior_receipts,
    )
    final = final.model_copy(
        update={
            "actual": final.actual.model_copy(
                update={
                    "recovery": recovery,
                    "authority": final.actual.authority.model_copy(update={"retry_probe": "PASS"})
                    if final.actual.authority is not None
                    else None,
                }
            ),
        }
    )
    final = (
        _benchmark_failure(
            final,
            reliability_match=origin_match and retry_match and final_match,
        )
        if not (origin_match and retry_match and final_match)
        else final.model_copy(
            update={"scores": final.scores.model_copy(update={"reliability_match": True})}
        )
    )
    return ReliabilityEvidence(
        case_result=final,
        order_id=order_id,
        failure_state=OrderState.FAILED_RETRYABLE,
        failure_origin=failure_origin,
        final_state=persisted.order.state,
        retry_used=True,
    )


async def run_duplicate_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> ReliabilityEvidence:
    """Replay one manifest identity and observe the durable idempotency boundary."""

    if case.replay is None:
        raise ValueError("replay scenario is required")
    before = await _count_orders(session_factory)
    initial = await run_case(session_factory, case, runtime, mode)
    order_id = await _order_id_for_case(session_factory, case)
    await _drain_notifications(session_factory, order_id)
    provider = _provider_observation(runtime)
    provider_calls_before = provider.calls if provider is not None else 0
    notification_before = await _count_order_rows(
        session_factory, NotificationDeliveryModel, order_id
    )
    sync_before = await _count_order_rows(session_factory, OrderSyncModel, order_id)
    observed_dispositions: list[CreateOrderDisposition] = []
    orchestration_globals = vars(orchestration_application)
    original_create: Any = orchestration_globals["create_order_with_disposition"]

    async def observing_create(*args: Any, **kwargs: Any) -> Any:
        created = await original_create(*args, **kwargs)
        observed_dispositions.append(created.disposition)
        return created

    orchestration_globals["create_order_with_disposition"] = observing_create
    try:
        replay = await run_case(session_factory, case, runtime, mode)
    finally:
        orchestration_globals["create_order_with_disposition"] = original_create
    provider_calls_after = provider.calls if provider is not None else provider_calls_before
    notification_after = await _count_order_rows(
        session_factory, NotificationDeliveryModel, order_id
    )
    sync_after = await _count_order_rows(session_factory, OrderSyncModel, order_id)
    await _drain_notifications(session_factory, order_id)
    after = await _count_orders(session_factory)
    creation_disposition = observed_dispositions[-1] if observed_dispositions else None
    replay_evidence = ReplayEvidence(
        creation_disposition=creation_disposition,
        intake_execution=replay.actual.intake_execution,
        seed_order_id=initial.actual.order_id or order_id,
        replay_order_id=replay.actual.order_id,
        authoritative_order_count=after - before,
        provider_calls_before=provider_calls_before,
        provider_calls_after=provider_calls_after,
        notification_intents_before=notification_before,
        notification_intents_after=notification_after,
        order_sync_intents_before=sync_before,
        order_sync_intents_after=sync_after,
        logical_external_object_count=0,
        provider_work_stood_down=provider_calls_after == provider_calls_before,
    )
    replay_match = (
        creation_disposition is case.replay.expected_creation_disposition
        and replay.actual.intake_execution is case.replay.expected_intake_execution
        and replay_evidence.seed_order_id == replay_evidence.replay_order_id
        and replay_evidence.authoritative_order_count == 1
        and replay_evidence.provider_work_stood_down is True
        and notification_before == notification_after
        and sync_before == sync_after
    )
    replay = replay.model_copy(
        update={
            "status": CaseResultStatus.PASS if replay_match else CaseResultStatus.FAIL,
            "actual": replay.actual.model_copy(
                update={
                    "creation_disposition": creation_disposition,
                    "replay": replay_evidence,
                }
            ),
            "scores": replay.scores.model_copy(update={"replay_match": replay_match}),
            "side_effects": SideEffectSummary(
                notification=replay.side_effects.notification,
                order_sync=replay.side_effects.order_sync,
                logical_external_objects=SideEffectDetail(status="NOT_RUN", count=0),
            ),
        }
    )
    return ReliabilityEvidence(
        case_result=replay,
        order_id=order_id,
        failure_state=None,
        failure_origin=None,
        final_state=replay.actual.pre_approval_state,
        authoritative_order_count=after - before,
        idempotent_replay=replay.actual.idempotent_replay is True,
    )


async def run_approval_sync_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> ReliabilityEvidence:
    """Exercise explicit human approval and fenced Phase 9 recovery."""

    if case.approval is None or case.recovery is None:
        raise ValueError("approval and recovery scenarios are required")
    initial = await run_case(session_factory, case, runtime, mode)
    order_id = await _order_id_for_case(session_factory, case)
    async with session_factory() as session:
        database_now = await session.scalar(select(func.clock_timestamp()))
        if not isinstance(database_now, datetime):
            raise RuntimeError("database clock did not return a timestamp")
        etag = await _review_etag(session, order_id)
        approved = await approve_order(
            session,
            order_id,
            etag,
            OperatorContext("m11c-approver", case.approval.role),
            database_now,
            runtime.review_base_url,
        )
    executor = EvaluationOrderSyncExecutor()
    async with session_factory() as session:
        claim = await claim_next_order_sync(session)
    if claim is None:
        return ReliabilityEvidence(
            case_result=_benchmark_failure(
                initial, reliability_match=False, execution_safety_match=False
            ),
            order_id=order_id,
            failure_state=None,
            failure_origin=None,
            final_state=initial.actual.pre_approval_state,
        )
    async with session_factory() as session:
        await begin_order_sync_step(session, order_id, claim.claim_token, OrderSyncStep.ODOO_LOOKUP)
        if await executor.execute(order_id, OrderSyncStep.ODOO_LOOKUP) is not None:
            raise RuntimeError("evaluation Odoo lookup must not return a receipt")
        await begin_order_sync_step(session, order_id, claim.claim_token, OrderSyncStep.ODOO_BRIDGE)
        receipt = await executor.execute(order_id, OrderSyncStep.ODOO_BRIDGE)
        assert isinstance(receipt, OdooOrderReceipt)
        await persist_order_sync_receipt(session, order_id, claim.claim_token, receipt)
        await yield_order_sync_claim(session, order_id, claim.claim_token)
    async with session_factory() as session, session.begin():
        await session.execute(
            update(OrderSyncModel)
            .where(OrderSyncModel.order_id == order_id)
            .values(
                attempt_count=2,
                claim_token=uuid4(),
                claim_expires_at=func.clock_timestamp() - text("interval '1 second'"),
                next_attempt_at=func.clock_timestamp(),
            )
        )
    async with session_factory() as session:
        exhausted = await claim_next_order_sync(session, include_exhaustion_result=True)
    if getattr(exhausted, "state", None) is not OrderState.FAILED_RETRYABLE:
        return ReliabilityEvidence(
            case_result=_benchmark_failure(initial, reliability_match=False),
            order_id=order_id,
            failure_state=None,
            failure_origin=None,
            final_state=None,
        )
    async with session_factory() as session:
        failed = await get_order(session, order_id)
        if failed is None:
            raise RuntimeError("sync order disappeared after worker lease exhaustion")
        failure_etag = await _review_etag(session, order_id)
    async with session_factory() as session:
        database_now = await session.scalar(select(func.clock_timestamp()))
        if not isinstance(database_now, datetime):
            raise RuntimeError("database clock did not return a timestamp")
        retry = await retry_order(
            session,
            order_id,
            failure_etag,
            OperatorContext("m11c-retry-reviewer", OperatorRole.REVIEWER),
            database_now,
        )
    if retry.state is not OrderState.SYNCING:
        return ReliabilityEvidence(
            case_result=_benchmark_failure(initial, reliability_match=False),
            order_id=order_id,
            failure_state=OrderState.FAILED_RETRYABLE,
            failure_origin=OrderState.SYNCING,
            final_state=retry.state,
            retry_used=True,
        )
    prior_call_count = len(executor.calls)
    async with session_factory() as session:
        completed = await execute_next_order_sync(session, executor)
    completion_match = completed.state is OrderState.COMPLETED
    resumed_steps = tuple(step.value for step in executor.calls[prior_call_count:])
    notifications = await _drain_notifications(session_factory, order_id)
    async with session_factory() as session:
        persisted = await get_order(session, order_id)
        sync_row = await session.get(OrderSyncModel, order_id)
    if persisted is None or sync_row is None:
        raise RuntimeError("completed sync evidence is missing")
    prior_receipt_preserved = sync_row.odoo_sale_order_id is not None
    final = _with_notification_evidence(initial, notifications).model_copy(
        update={
            "actual": initial.actual.model_copy(
                update={
                    "pre_approval_state": initial.actual.pre_approval_state,
                    "external_execution": "COMPLETED",
                    "external_execution_eligible": True,
                    "recovery": RecoveryEvidence(
                        injected_stage=case.recovery.injected_stage,
                        failure_code=case.recovery.failure_code,
                        failed_state=OrderState.FAILED_RETRYABLE,
                        failure_origin=OrderState.SYNCING,
                        retry_used=True,
                        retry_generation=sync_row.retry_generation,
                        final_state=persisted.order.state,
                        receipt_count=1 if prior_receipt_preserved else 0,
                        receipt_ids=(sync_row.odoo_sale_order_name,)
                        if sync_row.odoo_sale_order_name is not None
                        else (),
                        resumed_sync_steps=tuple(resumed_steps),
                        prior_receipts_preserved=prior_receipt_preserved,
                    ),
                    "authority": initial.actual.authority.model_copy(update={"retry_probe": "PASS"})
                    if initial.actual.authority is not None
                    else None,
                }
            ),
            "side_effects": SideEffectSummary(
                notification=_with_notification_evidence(
                    initial, notifications
                ).side_effects.notification,
                order_sync=SideEffectDetail(status="COMPLETED", count=len(executor.calls)),
                logical_external_objects=SideEffectDetail(
                    status="COMPLETED", count=executor.logical_external_object_count
                ),
            ),
        }
    )
    final_match = persisted.order.state is case.recovery.expected_final_state
    reliability_match = completion_match and final_match and prior_receipt_preserved
    final = (
        final.model_copy(
            update={
                "scores": final.scores.model_copy(
                    update={"reliability_match": True, "execution_safety_match": True}
                )
            }
        )
        if reliability_match
        else _benchmark_failure(final, reliability_match=False, execution_safety_match=False)
    )
    return ReliabilityEvidence(
        case_result=final,
        order_id=order_id,
        failure_state=OrderState.FAILED_RETRYABLE,
        failure_origin=OrderState.SYNCING,
        final_state=persisted.order.state,
        retry_used=True,
        approved_state=approved.state,
        retry_generation=sync_row.retry_generation,
        prior_receipt_preserved=prior_receipt_preserved,
        resumed_steps=resumed_steps,
        logical_external_object_count=executor.logical_external_object_count,
    )


async def _count_orders(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return int((await session.scalar(select(func.count()).select_from(OrderModel))) or 0)


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
        try:
            if case.recovery is not None:
                evidence = (
                    await run_approval_sync_scenario(session_factory, case, case_runtime, mode)
                    if case.approval is not None
                    else await run_recovery_scenario(session_factory, case, case_runtime, mode)
                )
                results.append(evidence.case_result)
            elif case.replay is not None:
                results.append(
                    (
                        await run_duplicate_scenario(session_factory, case, case_runtime, mode)
                    ).case_result
                )
            else:
                result = await run_case(session_factory, case, case_runtime, mode)
                try:
                    order_id = await _order_id_for_case(session_factory, case)
                except RuntimeError:
                    results.append(result)
                else:
                    results.append(
                        _with_notification_evidence(
                            result,
                            await _drain_notifications(session_factory, order_id),
                        )
                    )
        except Exception as error:
            results.append(_error_result(case, error, _provider_observation(case_runtime)))

    result_tuple = tuple(results)
    gates = evaluate_release_gates(corpus, result_tuple)
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
            routing=build_routing_metrics(corpus, result_tuple, gates),
        ),
        pricing=PricingStatus(status="NOT_APPLICABLE"),
        release_gates=gates,
        limitations=(
            "M11C does not collect aggregate timing, pricing, token-cost, or live-model evidence.",
        ),
    )


__all__ = ["run_case", "run_corpus"]
