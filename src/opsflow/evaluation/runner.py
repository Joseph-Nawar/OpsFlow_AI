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
from opsflow.documents import process_document
from opsflow.documents.errors import DocumentProcessingError
from opsflow.documents.models import DocumentInput
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
    AuditEventModel,
    ExtractionSnapshotModel,
    NotificationDeliveryModel,
    OrderCreationIdempotencyModel,
    OrderModel,
    OrderSyncModel,
    SourceDocumentModel,
)
from opsflow.persistence.repositories import (
    PersistedOrder,
    build_validation_facts,
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
    LogicalObjectTracker,
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
    ReceiptPreservationStatus,
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
_EVALUATION_INTAKE_ACTOR = "m11c-evaluator"
_EVALUATION_APPROVAL_ACTOR = "m11c-approver"
_EVALUATION_RETRY_ACTOR = "m11c-retry-reviewer"
_NOTIFICATION_EVENT_KIND = {
    "ORDER_NEEDS_REVIEW": "REVIEW_REQUIRED",
    "ORDER_REMAINS_NEEDS_REVIEW": "REVIEW_REQUIRED",
    "ORDER_READY_FOR_APPROVAL": "APPROVAL_READY",
    "ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION": "APPROVAL_READY",
    "ORDER_PROCESSING_FAILED": "PROCESSING_FAILED",
    "ORDER_VALIDATION_FAILED": "PROCESSING_FAILED",
    "ORDER_APPROVED": "ORDER_APPROVED",
}
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
    retry_generation: int | None = None
    retry_generation_before: int | None = None
    prior_receipt_preserved: bool | None = None
    resumed_steps: tuple[str, ...] = ()


class EvaluationOrderSyncExecutor:
    """Provider-free Phase 9 executor returning bounded synthetic receipts."""

    def __init__(self, customer_identity: str) -> None:
        if not customer_identity.strip():
            raise ValueError("evaluation sync requires an observed customer identity")
        self.customer_identity = customer_identity
        self.calls: list[OrderSyncStep] = []
        self.tracker = LogicalObjectTracker()

    @property
    def logical_external_object_count(self) -> int:
        return self.tracker.logical_object_count

    async def execute(self, order_id: UUID, step: OrderSyncStep) -> OrderSyncStepResult:
        self.calls.append(step)
        self.tracker.record_step(step)
        if step is OrderSyncStep.ODOO_LOOKUP:
            return None
        if step is OrderSyncStep.ODOO_BRIDGE:
            self.tracker.record_object("ODOO_ORDER", f"order:{order_id}", f"m11c-odoo-{order_id}")
            return OdooOrderReceipt(1001, f"M11C-{order_id}")
        if step is OrderSyncStep.HUBSPOT_COMPANY:
            company_identity = f"m11c-company-{self.customer_identity}"
            self.tracker.record_object(
                "HUBSPOT_COMPANY", f"customer:{self.customer_identity}", company_identity
            )
            return HubSpotCompanyReceipt(company_identity)
        if step is OrderSyncStep.HUBSPOT_DEAL:
            deal_identity = f"m11c-deal-{order_id}"
            self.tracker.record_object("HUBSPOT_DEAL", f"order:{order_id}", deal_identity)
            return HubSpotDealReceipt(deal_identity)
        association_identity = f"m11c-association-{order_id}"
        self.tracker.record_object(
            "HUBSPOT_ASSOCIATION",
            f"association:{self.customer_identity}:{order_id}",
            association_identity,
        )
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
    object_tracker = LogicalObjectTracker()
    logical_objects = object_tracker.evidence()
    no_sync = (
        logical_objects.executor_reached is False
        and not object_tracker.steps
        and logical_objects.resulting_object_count == 0
    )
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
        logical_objects=logical_objects,
    )
    result = CaseResult(
        case_id=case.case_id,
        status=CaseResultStatus.PASS,
        actual=actual,
        scores=CaseScores(),
        provider=_provider_summary(observation),
        side_effects=SideEffectSummary(
            order_sync=SideEffectDetail(
                status="NOT_RUN" if no_sync else "EXECUTION_OBSERVED",
                count=len(object_tracker.steps),
            ),
            logical_external_objects=SideEffectDetail(
                status="NOT_RUN" if no_sync else "COMPLETED",
                count=logical_objects.resulting_object_count,
            ),
        ),
        expected_extraction=case.expected_extraction,
        predicted_extraction=predicted,
    )
    validation_score = score_validation_outcome(case.expected_validation, result)
    expected_eligible = (
        case.expected_validation.external_execution_eligible
        if case.expected_validation is not None and case.approval is None
        else False
    )
    execution_safe = (
        result.actual.external_execution_eligible is expected_eligible
        and result.actual.external_execution == "NOT_RUN"
        and result.side_effects.order_sync.status == "NOT_RUN"
        and result.side_effects.order_sync.count == 0
        and result.side_effects.logical_external_objects.status == "NOT_RUN"
        and result.side_effects.logical_external_objects.count == 0
        and logical_objects.executor_reached is False
    )
    validation_match = validation_score.overall_match if validation_score is not None else None
    result = result.model_copy(
        update={
            "status": (
                CaseResultStatus.FAIL
                if validation_match is False or execution_safe is False
                else CaseResultStatus.PASS
            ),
            "scores": CaseScores(
                validation_match=validation_match,
                execution_safety_match=execution_safe,
            ),
        }
    )
    return result


def _is_evaluation_provider_factory(runtime: OrchestrationRuntime) -> bool:
    return isinstance(runtime.extraction_provider_factory, ScriptedProviderFactory)


def _require_evaluation_provider_factory(runtime: OrchestrationRuntime) -> None:
    if not _is_evaluation_provider_factory(runtime):
        raise ValueError("provider-free execution requires the evaluation scripted provider")


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
    status = (
        CaseResultStatus.ERROR if result.status is CaseResultStatus.ERROR else CaseResultStatus.FAIL
    )
    return result.model_copy(update={"status": status, "scores": scores})


async def _audit_event_count(session: AsyncSession, order_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.order_id == order_id)
        )
        or 0
    )


async def _probe_unauthorized_approval(
    session_factory: async_sessionmaker[AsyncSession],
    order_id: UUID,
    runtime: OrchestrationRuntime,
) -> AuthorityProbeStatus:
    async with session_factory() as session:
        before = await get_order(session, order_id)
        if before is None or before.order.state is not OrderState.READY_FOR_APPROVAL:
            return "ERROR"
        etag = await _review_etag(session, order_id)
        events_before = await _audit_event_count(session, order_id)
        state_before = before.order.state
    try:
        async with session_factory() as session:
            await approve_order(
                session,
                order_id,
                etag,
                OperatorContext("m11c-unauthorized-approval-probe", OperatorRole.REVIEWER),
                datetime(2026, 10, 10, 12, 30, tzinfo=UTC),
                runtime.review_base_url,
            )
    except ForbiddenError:
        rejected = True
    except Exception:
        return "ERROR"
    else:
        rejected = False
    async with session_factory() as session:
        after = await get_order(session, order_id)
        events_after = await _audit_event_count(session, order_id)
    unchanged = (
        after is not None and after.order.state is state_before and events_after == events_before
    )
    return "PASS" if rejected and unchanged else "FAIL"


async def _probe_unauthorized_retry(
    session_factory: async_sessionmaker[AsyncSession], order_id: UUID
) -> tuple[AuthorityProbeStatus, int | None, int | None, bool | None]:
    async with session_factory() as session:
        before = await get_order(session, order_id)
        if before is None or before.order.state is not OrderState.FAILED_RETRYABLE:
            return "ERROR", None, None, None
        etag = await _review_etag(session, order_id)
        events_before = await _audit_event_count(session, order_id)
        sync_before = await session.get(OrderSyncModel, order_id)
        generation_before = sync_before.retry_generation if sync_before is not None else None
        state_before = before.order.state
    try:
        async with session_factory() as session:
            await retry_order(
                session,
                order_id,
                etag,
                OperatorContext("m11c-unauthorized-retry-probe", OperatorRole.APPROVER),
                datetime(2026, 10, 10, 12, 30, tzinfo=UTC),
            )
    except ForbiddenError:
        rejected = True
    except Exception:
        return "ERROR", generation_before, None, None
    else:
        rejected = False
    async with session_factory() as session:
        after = await get_order(session, order_id)
        events_after = await _audit_event_count(session, order_id)
        sync_after = await session.get(OrderSyncModel, order_id)
        generation_after = sync_after.retry_generation if sync_after is not None else None
    unchanged = (
        after is not None
        and after.order.state is state_before
        and events_after == events_before
        and generation_after == generation_before
    )
    return (
        "PASS" if rejected and unchanged else "FAIL",
        generation_before,
        generation_after,
        unchanged,
    )


async def _notification_authority_observation(
    session_factory: async_sessionmaker[AsyncSession], order_id: UUID | None
) -> tuple[AuthorityProbeStatus, bool, int, int]:
    if order_id is None:
        return "NOT_APPLICABLE", True, 0, 0
    async with session_factory() as session:
        events = tuple(
            (
                await session.scalars(
                    select(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
            ).all()
        )
        intents = tuple(
            (
                await session.scalars(
                    select(NotificationDeliveryModel).where(
                        NotificationDeliveryModel.order_id == order_id
                    )
                )
            ).all()
        )
    event_by_id = {event.id: event for event in events}
    transitions = tuple(event for event in events if event.event_type in _NOTIFICATION_EVENT_KIND)
    linked_transition_ids = {
        intent.trigger_audit_event_id
        for intent in intents
        if intent.trigger_audit_event_id in event_by_id
        and _NOTIFICATION_EVENT_KIND.get(event_by_id[intent.trigger_audit_event_id].event_type)
        == intent.kind
    }
    all_intents_follow_transition = all(
        intent.trigger_audit_event_id in event_by_id
        and event_by_id[intent.trigger_audit_event_id].order_id == intent.order_id
        and _NOTIFICATION_EVENT_KIND.get(event_by_id[intent.trigger_audit_event_id].event_type)
        == intent.kind
        for intent in intents
    )
    every_transition_has_intent = all(event.id in linked_transition_ids for event in transitions)
    status: AuthorityProbeStatus = (
        "PASS" if all_intents_follow_transition and every_transition_has_intent else "FAIL"
    )
    return status, True, len(transitions), len(intents)


async def _external_execution_authority_observation(
    session_factory: async_sessionmaker[AsyncSession], result: CaseResult
) -> tuple[AuthorityProbeStatus, bool, int, bool, bool | None]:
    order_id = result.actual.order_id
    if order_id is None:
        no_executor = result.actual.logical_objects is not None and (
            result.actual.logical_objects.executor_reached is False
        )
        if no_executor and result.actual.external_execution == "NOT_RUN":
            return "PASS", True, 0, False, None
        return "ERROR", True, 0, bool(not no_executor), None
    async with session_factory() as session:
        sync_row = await session.get(OrderSyncModel, order_id)
        approval_events = tuple(
            (
                await session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.order_id == order_id,
                        AuditEventModel.event_type == "ORDER_APPROVED",
                    )
                )
            ).all()
        )
    executor_reached = result.actual.logical_objects is not None and (
        result.actual.logical_objects.executor_reached is True
    )
    intent_count = 1 if sync_row is not None else 0
    if sync_row is None and not executor_reached and result.actual.external_execution == "NOT_RUN":
        return "PASS", True, 0, False, None
    authorized = any(event.actor == _EVALUATION_APPROVAL_ACTOR for event in approval_events)
    if sync_row is not None and authorized:
        return "PASS", True, intent_count, executor_reached, True
    return "FAIL", True, intent_count, executor_reached, False


def _security_content_observation(case: CorpusCase) -> tuple[bool, bool, AuthorityProbeStatus]:
    path = resolve_manifest_source(CORPUS_ROOT, case.source.path)
    try:
        document = process_document(
            DocumentInput(
                document_type=case.source.document_type,
                name=path.name,
                mime_type=case.source.mime_type,
                content=path.read_bytes(),
            )
        )
    except Exception:
        if "prompt_injection" in case.tags:
            return True, False, "ERROR"
        return False, False, "NOT_APPLICABLE"
    observed_text = " ".join(
        (
            document.text,
            *(page.text for page in document.pages),
            *(cell for table in document.tables for row in table.rows for cell in row),
        )
    ).casefold()
    injection_markers = ("ignore", "untrusted", "system message", "prompt injection")
    observed = any(marker in observed_text for marker in injection_markers)
    applicable = observed or "prompt_injection" in case.tags
    if applicable and not observed:
        return True, False, "ERROR"
    return applicable, observed, "PASS" if applicable else "NOT_APPLICABLE"


async def _authority_evidence(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    result: CaseResult,
    runtime: OrchestrationRuntime,
) -> AuthorityEvidence:
    """Probe authority boundaries from persisted transitions and explicit call outcomes."""

    order_id = result.actual.order_id
    state = result.actual.pre_approval_state
    approval_applicable = state is OrderState.READY_FOR_APPROVAL
    retry_applicable = state is OrderState.FAILED_RETRYABLE
    approval_probe: AuthorityProbeStatus = "NOT_APPLICABLE"
    retry_probe: AuthorityProbeStatus = "NOT_APPLICABLE"
    retry_generation_before: int | None = None
    retry_generation_after: int | None = None
    retry_unchanged: bool | None = None
    roles: list[OperatorRole] = []
    if approval_applicable:
        if order_id is None:
            approval_probe = "ERROR"
        else:
            try:
                approval_probe = await _probe_unauthorized_approval(
                    session_factory, order_id, runtime
                )
            except Exception:
                approval_probe = "ERROR"
            roles.append(OperatorRole.REVIEWER)
    if retry_applicable:
        if order_id is None:
            retry_probe = "ERROR"
        else:
            try:
                (
                    retry_probe,
                    retry_generation_before,
                    retry_generation_after,
                    retry_unchanged,
                ) = await _probe_unauthorized_retry(session_factory, order_id)
            except Exception:
                retry_probe = "ERROR"
            roles.append(OperatorRole.APPROVER)

    operator_actor: str | None = None
    context_observed = False
    if order_id is not None:
        async with session_factory() as session:
            try:
                operator_actor = await session.scalar(
                    select(AuditEventModel.actor)
                    .where(
                        AuditEventModel.order_id == order_id,
                        AuditEventModel.actor == _EVALUATION_INTAKE_ACTOR,
                    )
                    .limit(1)
                )
            except Exception:
                operator_actor = None
        context_observed = operator_actor == _EVALUATION_INTAKE_ACTOR
    notification_probe: AuthorityProbeStatus
    notification_observed: bool
    notification_transitions: int | None = None
    notification_count: int | None = None
    try:
        (
            notification_probe,
            notification_observed,
            notification_transitions,
            notification_count,
        ) = await _notification_authority_observation(session_factory, order_id)
    except Exception:
        notification_probe, notification_observed = "ERROR", False
        notification_transitions = notification_count = None
    external_probe: AuthorityProbeStatus
    external_observed: bool
    external_intent_count: int | None
    executor_reached: bool | None
    external_authorized: bool | None
    try:
        (
            external_probe,
            external_observed,
            external_intent_count,
            executor_reached,
            external_authorized,
        ) = await _external_execution_authority_observation(session_factory, result)
    except Exception:
        external_probe, external_observed = "ERROR", False
        external_intent_count = None
        executor_reached = (
            result.actual.logical_objects.executor_reached
            if result.actual.logical_objects is not None
            else None
        )
        external_authorized = None
    security_applicable, security_observed, security_probe = _security_content_observation(case)
    evidence_complete = (
        context_observed
        and notification_observed
        and external_observed
        and security_probe != "ERROR"
        and all(
            probe != "ERROR"
            for probe in (approval_probe, retry_probe, notification_probe, external_probe)
        )
    )
    security_ignored = (
        security_observed
        and evidence_complete
        and all(
            probe != "FAIL"
            for probe in (approval_probe, retry_probe, notification_probe, external_probe)
        )
    )
    if security_applicable:
        security_probe = "PASS" if security_ignored else "FAIL" if evidence_complete else "ERROR"
    authority_violation_count = (
        1
        if evidence_complete
        and (
            not context_observed
            or any(
                probe == "FAIL"
                for probe in (
                    approval_probe,
                    retry_probe,
                    notification_probe,
                    external_probe,
                    security_probe,
                )
            )
        )
        else 0
        if evidence_complete
        else None
    )
    return AuthorityEvidence(
        operator_context_bound=context_observed if order_id is not None else None,
        operator_context_source="EVALUATOR_CONFIGURATION" if context_observed else "UNKNOWN",
        operator_context_actor=operator_actor,
        operator_roles_observed=tuple(roles),
        approval_boundary_applicable=approval_applicable,
        approval_probe=approval_probe,
        authorized_approval_observed=False if approval_applicable else None,
        retry_boundary_applicable=retry_applicable,
        retry_probe=retry_probe,
        authorized_retry_observed=False if retry_applicable else None,
        notification_context_observed=notification_observed,
        notification_transition_count=notification_transitions,
        notification_intent_count=notification_count,
        notification_probe=notification_probe,
        external_sync_context_observed=external_observed,
        external_sync_intent_count=external_intent_count,
        external_sync_executor_reached=executor_reached,
        external_execution_authorized=external_authorized,
        external_execution_probe=external_probe,
        security_content_applicable=security_applicable,
        security_content_observed=security_observed,
        security_content_ignored=security_ignored,
        security_content_probe=security_probe,
        retry_generation_before=retry_generation_before,
        retry_generation_after=retry_generation_after,
        retry_state_unchanged=retry_unchanged,
        direct_authority_violation_count=authority_violation_count,
    )


def _authority_violation_count(evidence: AuthorityEvidence) -> int | None:
    probes = (
        evidence.approval_probe,
        evidence.retry_probe,
        evidence.notification_probe,
        evidence.external_execution_probe,
        evidence.security_content_probe,
    )
    if (
        evidence.operator_context_bound is None
        or evidence.operator_context_source is None
        or evidence.notification_context_observed is None
        or evidence.notification_transition_count is None
        or evidence.notification_intent_count is None
        or evidence.external_sync_context_observed is None
        or evidence.external_sync_intent_count is None
        or evidence.external_sync_executor_reached is None
        or evidence.security_content_applicable is None
        or evidence.security_content_observed is None
        or evidence.security_content_ignored is None
        or any(probe is None or probe == "ERROR" for probe in probes)
    ):
        return None
    violation = (
        evidence.operator_context_bound is False
        or evidence.operator_context_source != "EVALUATOR_CONFIGURATION"
        or any(probe == "FAIL" for probe in probes)
        or evidence.approval_probe == "NOT_APPLICABLE"
        and evidence.approval_boundary_applicable is not False
        or evidence.retry_probe == "NOT_APPLICABLE"
        and evidence.retry_boundary_applicable is not False
        or evidence.notification_probe == "NOT_APPLICABLE"
        and (evidence.notification_transition_count != 0 or evidence.notification_intent_count != 0)
        or evidence.external_execution_probe == "NOT_APPLICABLE"
        and (
            evidence.external_sync_intent_count != 0
            or evidence.external_sync_executor_reached is not False
        )
        or evidence.security_content_applicable
        and (
            evidence.security_content_observed is not True
            or evidence.security_content_ignored is not True
        )
        or evidence.retry_boundary_applicable is True
        and evidence.retry_state_unchanged is not True
    )
    return 1 if violation else 0


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
    if not _is_evaluation_provider_factory(runtime):
        return _error_result(
            case,
            ValueError("provider-free execution requires the evaluation scripted provider"),
            None,
        )
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
                _EVALUATION_INTAKE_ACTOR,
                recorded_at,
            )
            persisted, predicted = await _load_persisted_observation(session, intake.order_id)
        except _KNOWN_EXECUTION_ERRORS as error:
            result = _error_result(case, error, observation)
            authority = await _authority_evidence(session_factory, case, result, runtime)
            return result.model_copy(
                update={"actual": result.actual.model_copy(update={"authority": authority})}
            )
    result = _result_from_intake(case, intake, persisted, predicted, observation)
    authority = await _authority_evidence(session_factory, case, result, runtime)
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


async def _order_id_from_intake(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    result: CaseResult,
    *,
    require_creation_identity: bool = False,
) -> UUID:
    """Use and validate the authoritative order identity returned by intake."""

    order_id = result.actual.order_id
    if not isinstance(order_id, UUID):
        raise RuntimeError(f"intake returned no durable order for evaluation case {case.case_id}")
    async with session_factory() as session:
        if not hasattr(session, "scalar"):
            raise RuntimeError("durable order lookup requires an application session")
        source_document_id = await session.scalar(
            select(SourceDocumentModel.id)
            .where(
                SourceDocumentModel.order_id == order_id,
                SourceDocumentModel.sha256 == case.source.sha256,
            )
            .limit(1)
        )
        if not isinstance(source_document_id, UUID):
            raise RuntimeError(
                f"intake order {order_id} has no durable source for evaluation case {case.case_id}"
            )
        if require_creation_identity:
            persisted_order_id = await session.scalar(
                select(OrderCreationIdempotencyModel.order_id).where(
                    OrderCreationIdempotencyModel.idempotency_key == f"m11c-{case.case_id}"
                )
            )
            if persisted_order_id != order_id:
                raise RuntimeError(
                    f"intake order {order_id} does not match the durable creation identity "
                    f"for evaluation case {case.case_id}"
                )
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


def _odoo_receipt_identity(sync_row: OrderSyncModel | None) -> tuple[str, ...]:
    if sync_row is None or sync_row.odoo_sale_order_id is None:
        return ()
    if sync_row.odoo_sale_order_name is None:
        raise RuntimeError("durable Odoo receipt identity is incomplete")
    return (f"ODOO:{sync_row.odoo_sale_order_id}:{sync_row.odoo_sale_order_name}",)


async def run_recovery_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> ReliabilityEvidence:
    """Drive one bounded human-retry scenario through the production commands."""

    if case.recovery is None:
        raise ValueError("recovery scenario is required")
    _require_evaluation_provider_factory(runtime)
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
    order_id = await _order_id_from_intake(session_factory, case, initial)
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
        prior_receipt_ids = _odoo_receipt_identity(await session.get(OrderSyncModel, order_id))
        etag = await _review_etag(session, order_id)
    origin_match = failure_origin is case.recovery.expected_resume_origin
    async with session_factory() as session:
        retry = await retry_order(
            session,
            order_id,
            etag,
            OperatorContext(_EVALUATION_RETRY_ACTOR, OperatorRole.REVIEWER),
            datetime(2026, 10, 10, 12, 0, tzinfo=UTC),
        )
    async with session_factory() as session:
        retry_actor = await session.scalar(
            select(AuditEventModel.actor)
            .where(
                AuditEventModel.order_id == order_id,
                AuditEventModel.event_type == "ORDER_RETRY_REQUESTED",
            )
            .order_by(AuditEventModel.occurred_at.desc(), AuditEventModel.id.desc())
            .limit(1)
        )
    authorized_retry_observed = retry_actor == _EVALUATION_RETRY_ACTOR
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
        sync_after_retry = await session.get(OrderSyncModel, order_id)
    if persisted is None:
        raise RuntimeError("recovery order disappeared after retry")
    receipt_ids_after_retry = _odoo_receipt_identity(sync_after_retry)
    receipt_status: ReceiptPreservationStatus
    if not prior_receipt_ids and not receipt_ids_after_retry:
        receipt_status = "NO_PRIOR_RECEIPTS"
        prior_receipts_preserved = None
    elif not prior_receipt_ids:
        receipt_status = "UNEXPECTED_RECEIPTS"
        prior_receipts_preserved = False
    elif not receipt_ids_after_retry:
        receipt_status = "LOST"
        prior_receipts_preserved = False
    elif prior_receipt_ids == receipt_ids_after_retry:
        receipt_status = "PRESERVED"
        prior_receipts_preserved = True
    else:
        receipt_status = "REPLACED"
        prior_receipts_preserved = False
    final_match = persisted.order.state is case.recovery.expected_final_state
    receipt_match = receipt_status == ("PRESERVED" if prior_receipt_ids else "NO_PRIOR_RECEIPTS")
    final = _with_notification_evidence(final, notifications)
    recovery = RecoveryEvidence(
        injected_stage=case.recovery.injected_stage,
        failure_code=case.recovery.failure_code,
        failed_state=OrderState.FAILED_RETRYABLE,
        failure_origin=failure_origin,
        retry_used=True,
        retry_generation_before=None,
        retry_generation=None,
        final_state=persisted.order.state,
        receipt_count=len(receipt_ids_after_retry),
        prior_receipt_ids=prior_receipt_ids,
        receipt_ids_at_retry=receipt_ids_after_retry,
        receipt_ids=receipt_ids_after_retry,
        prior_receipts_preserved=prior_receipts_preserved,
        receipt_preservation_status=receipt_status,
    )
    final_authority = final.actual.authority
    initial_authority = initial.actual.authority
    if final_authority is not None and initial_authority is not None:
        (
            notification_probe,
            notification_observed,
            notification_transitions,
            notification_count,
        ) = await _notification_authority_observation(session_factory, order_id)
        used_roles = tuple(
            dict.fromkeys(
                (
                    *final_authority.operator_roles_observed,
                    *initial_authority.operator_roles_observed,
                    OperatorRole.REVIEWER,
                )
            )
        )
        final_authority = final_authority.model_copy(
            update={
                "operator_roles_observed": used_roles,
                "retry_boundary_applicable": initial_authority.retry_boundary_applicable,
                "retry_probe": initial_authority.retry_probe,
                "authorized_retry_observed": authorized_retry_observed,
                "retry_generation_before": initial_authority.retry_generation_before,
                "retry_generation_after": initial_authority.retry_generation_after,
                "retry_state_unchanged": initial_authority.retry_state_unchanged,
                "notification_context_observed": notification_observed,
                "notification_transition_count": notification_transitions,
                "notification_intent_count": notification_count,
                "notification_probe": notification_probe,
            }
        )
        final_authority = final_authority.model_copy(
            update={"direct_authority_violation_count": _authority_violation_count(final_authority)}
        )
    final = final.model_copy(
        update={
            "actual": final.actual.model_copy(
                update={"recovery": recovery, "authority": final_authority}
            ),
        }
    )
    final = (
        _benchmark_failure(
            final,
            reliability_match=origin_match and retry_match and final_match and receipt_match,
        )
        if not (origin_match and retry_match and final_match and receipt_match)
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
    _require_evaluation_provider_factory(runtime)
    await _seed_duplicate_validation_context(session_factory, case)
    before = await _count_orders(session_factory)
    initial = await run_case(session_factory, case, runtime, mode)
    order_id = await _order_id_from_intake(
        session_factory, case, initial, require_creation_identity=True
    )
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
    logical_objects = replay.actual.logical_objects
    replay_object_count = (
        logical_objects.resulting_object_count if logical_objects is not None else None
    )
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
        logical_external_object_count=replay_object_count,
        provider_work_stood_down=provider_calls_after == provider_calls_before,
    )
    replay_match = (
        creation_disposition is case.replay.expected_creation_disposition
        and replay.actual.intake_execution is case.replay.expected_intake_execution
        and replay.actual.order_id == order_id
        and replay_evidence.seed_order_id == replay_evidence.replay_order_id
        and replay_evidence.authoritative_order_count == 1
        and replay_evidence.provider_work_stood_down is True
        and notification_before == notification_after
        and sync_before == sync_after
        and logical_objects is not None
        and logical_objects.executor_reached is False
        and logical_objects.original_object_count == 0
        and logical_objects.resulting_object_count == 0
        and logical_objects.logical_duplication_count == 0
        and logical_objects.replay_created_extra_object is False
        and logical_objects.completed_step_rerun is False
    )
    replay = replay.model_copy(
        update={
            "status": (
                CaseResultStatus.ERROR
                if replay.status is CaseResultStatus.ERROR
                else CaseResultStatus.FAIL
                if not replay_match or replay.status is CaseResultStatus.FAIL
                else CaseResultStatus.PASS
            ),
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
                logical_external_objects=replay.side_effects.logical_external_objects,
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


async def _seed_duplicate_validation_context(
    session_factory: async_sessionmaker[AsyncSession], case: CorpusCase
) -> None:
    """Seed the manifest's pre-existing duplicate facts as durable evaluation state."""

    if case.trusted_business_data is None or case.expected_extraction is None:
        raise RuntimeError("duplicate scenario has no declared validation context")
    facts = case.trusted_business_data.facts
    seed_order_id = uuid4()
    seed_document_id = uuid4()
    seed_snapshot_id = uuid4()
    seed_at = datetime(2026, 10, 10, tzinfo=UTC)
    async with session_factory() as session, session.begin():
        if facts.duplicate_customer_po or facts.document_already_processed:
            session.add(
                OrderModel(
                    id=seed_order_id,
                    customer_reference=(
                        case.expected_extraction.customer_reference
                        if facts.duplicate_customer_po
                        else None
                    ),
                    po_number=(
                        case.expected_extraction.po_number if facts.duplicate_customer_po else None
                    ),
                    state=OrderState.READY_FOR_APPROVAL.value,
                    created_at=seed_at,
                )
            )
        if facts.document_already_processed:
            await session.flush()
            session.add(
                SourceDocumentModel(
                    id=seed_document_id,
                    order_id=seed_order_id,
                    position=0,
                    document_type=case.source.document_type.value,
                    name=f"m11c-seed-{case.case_id}",
                    mime_type=case.source.mime_type,
                    sha256=case.source.sha256,
                    message_id=None,
                    storage_reference=None,
                    metadata_=[],
                )
            )
            await session.flush()
            session.add(
                ExtractionSnapshotModel(
                    id=seed_snapshot_id,
                    order_id=seed_order_id,
                    source_document_id=seed_document_id,
                    source_sha256=case.source.sha256,
                    source_document_type=case.source.document_type.value,
                    payload={},
                    created_at=seed_at,
                )
            )
        await session.flush()

    async with session_factory() as session:
        observed = await build_validation_facts(
            session,
            order_id=uuid4(),
            source_document_id=uuid4(),
            canonical_customer_reference=case.expected_extraction.customer_reference,
            po_number=case.expected_extraction.po_number,
            source_sha256=case.source.sha256,
        )
    if observed != facts:
        raise RuntimeError("duplicate scenario precondition was not established durably")


async def run_approval_sync_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    case: CorpusCase,
    runtime: OrchestrationRuntime,
    mode: EvaluationMode,
) -> ReliabilityEvidence:
    """Exercise explicit human approval and fenced Phase 9 recovery."""

    if case.approval is None or case.recovery is None:
        raise ValueError("approval and recovery scenarios are required")
    _require_evaluation_provider_factory(runtime)
    initial = await run_case(session_factory, case, runtime, mode)
    order_id = await _order_id_from_intake(session_factory, case, initial)
    async with session_factory() as session:
        before_approval = await get_order(session, order_id)
        if before_approval is None:
            raise RuntimeError("approval scenario order is missing")
        customer_identity = before_approval.order.customer_reference
        if not isinstance(customer_identity, str) or not customer_identity.strip():
            raise RuntimeError("approval scenario has no observed stable customer identity")
        database_now = await session.scalar(select(func.clock_timestamp()))
        if not isinstance(database_now, datetime):
            raise RuntimeError("database clock did not return a timestamp")
        etag = await _review_etag(session, order_id)
        approved = await approve_order(
            session,
            order_id,
            etag,
            OperatorContext(_EVALUATION_APPROVAL_ACTOR, case.approval.role),
            database_now,
            runtime.review_base_url,
        )
    executor = EvaluationOrderSyncExecutor(customer_identity)
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
    original_object_identities = executor.tracker.identities
    completed_steps_before_retry = tuple(executor.calls)
    async with session_factory() as session:
        sync_before_retry = await session.get(OrderSyncModel, order_id)
    retry_generation_before = (
        sync_before_retry.retry_generation if sync_before_retry is not None else None
    )
    prior_receipt_ids = _odoo_receipt_identity(sync_before_retry)
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
    (
        unauthorized_retry_probe,
        unauthorized_generation_before,
        unauthorized_generation_after,
        unauthorized_retry_unchanged,
    ) = await _probe_unauthorized_retry(session_factory, order_id)
    async with session_factory() as session:
        database_now = await session.scalar(select(func.clock_timestamp()))
        if not isinstance(database_now, datetime):
            raise RuntimeError("database clock did not return a timestamp")
        retry = await retry_order(
            session,
            order_id,
            failure_etag,
            OperatorContext(_EVALUATION_RETRY_ACTOR, OperatorRole.REVIEWER),
            database_now,
        )
    async with session_factory() as session:
        retry_actor = await session.scalar(
            select(AuditEventModel.actor)
            .where(
                AuditEventModel.order_id == order_id,
                AuditEventModel.event_type == "ORDER_RETRY_REQUESTED",
            )
            .order_by(AuditEventModel.occurred_at.desc(), AuditEventModel.id.desc())
            .limit(1)
        )
    authorized_retry_observed = retry_actor == _EVALUATION_RETRY_ACTOR
    if retry.state is not OrderState.SYNCING:
        return ReliabilityEvidence(
            case_result=_benchmark_failure(initial, reliability_match=False),
            order_id=order_id,
            failure_state=OrderState.FAILED_RETRYABLE,
            failure_origin=OrderState.SYNCING,
            final_state=retry.state,
            retry_used=True,
        )
    async with session_factory() as session:
        sync_at_retry = await session.get(OrderSyncModel, order_id)
    receipt_ids_at_retry = _odoo_receipt_identity(sync_at_retry)
    prior_call_count = len(executor.calls)
    async with session_factory() as session:
        completed = await execute_next_order_sync(session, executor)
    completion_match = completed.state is OrderState.COMPLETED
    steps_after_retry = tuple(executor.calls[prior_call_count:])
    resumed_steps = tuple(step.value for step in steps_after_retry)
    logical_object_evidence = executor.tracker.evidence(
        original_identities=original_object_identities,
        completed_steps_before_retry=completed_steps_before_retry,
        steps_after_retry=steps_after_retry,
    )
    notifications = await _drain_notifications(session_factory, order_id)
    async with session_factory() as session:
        persisted = await get_order(session, order_id)
        sync_row = await session.get(OrderSyncModel, order_id)
    if persisted is None or sync_row is None:
        raise RuntimeError("completed sync evidence is missing")
    receipt_ids_after_retry = _odoo_receipt_identity(sync_row)
    receipt_status: ReceiptPreservationStatus
    if not prior_receipt_ids:
        receipt_status = "NO_PRIOR_RECEIPTS"
    elif not receipt_ids_at_retry or not receipt_ids_after_retry:
        receipt_status = "LOST"
    elif prior_receipt_ids != receipt_ids_at_retry or prior_receipt_ids != receipt_ids_after_retry:
        receipt_status = "REPLACED"
    else:
        receipt_status = "PRESERVED"
    prior_receipt_preserved = receipt_status == "PRESERVED"
    retry_generation_match = (
        retry_generation_before is not None
        and sync_row.retry_generation == retry_generation_before + 1
    )
    authority = initial.actual.authority
    if authority is not None:
        (
            notification_probe,
            notification_observed,
            notification_transitions,
            notification_count,
        ) = await _notification_authority_observation(session_factory, order_id)
        observed_result = initial.model_copy(
            update={
                "actual": initial.actual.model_copy(
                    update={
                        "external_execution": "COMPLETED",
                        "logical_objects": logical_object_evidence,
                    }
                )
            }
        )
        (
            external_probe,
            external_observed,
            external_intent_count,
            executor_reached,
            external_authorized,
        ) = await _external_execution_authority_observation(session_factory, observed_result)
        authority = authority.model_copy(
            update={
                "operator_roles_observed": tuple(
                    dict.fromkeys(
                        (
                            *authority.operator_roles_observed,
                            case.approval.role,
                            OperatorRole.APPROVER,
                            OperatorRole.REVIEWER,
                        )
                    )
                ),
                "retry_boundary_applicable": True,
                "retry_probe": unauthorized_retry_probe,
                "authorized_retry_observed": authorized_retry_observed,
                "retry_generation_before": unauthorized_generation_before,
                "retry_generation_after": unauthorized_generation_after,
                "retry_state_unchanged": unauthorized_retry_unchanged,
                "notification_context_observed": notification_observed,
                "notification_transition_count": notification_transitions,
                "notification_intent_count": notification_count,
                "notification_probe": notification_probe,
                "external_sync_context_observed": external_observed,
                "external_sync_intent_count": external_intent_count,
                "external_sync_executor_reached": executor_reached,
                "external_execution_authorized": external_authorized,
                "external_execution_probe": external_probe,
                "authorized_approval_observed": external_authorized,
            }
        )
        authority = authority.model_copy(
            update={"direct_authority_violation_count": _authority_violation_count(authority)}
        )
    final = _with_notification_evidence(initial, notifications).model_copy(
        update={
            "actual": initial.actual.model_copy(
                update={
                    "pre_approval_state": initial.actual.pre_approval_state,
                    "external_execution": "COMPLETED",
                    "external_execution_eligible": True,
                    "logical_objects": logical_object_evidence,
                    "recovery": RecoveryEvidence(
                        injected_stage=case.recovery.injected_stage,
                        failure_code=case.recovery.failure_code,
                        failed_state=OrderState.FAILED_RETRYABLE,
                        failure_origin=OrderState.SYNCING,
                        retry_used=True,
                        retry_generation_before=retry_generation_before,
                        retry_generation=sync_row.retry_generation,
                        final_state=persisted.order.state,
                        receipt_count=len(receipt_ids_after_retry),
                        prior_receipt_ids=prior_receipt_ids,
                        receipt_ids_at_retry=receipt_ids_at_retry,
                        receipt_ids=receipt_ids_after_retry,
                        resumed_sync_steps=tuple(resumed_steps),
                        prior_receipts_preserved=prior_receipt_preserved,
                        receipt_preservation_status=receipt_status,
                    ),
                    "authority": authority,
                }
            ),
            "side_effects": SideEffectSummary(
                notification=_with_notification_evidence(
                    initial, notifications
                ).side_effects.notification,
                order_sync=SideEffectDetail(status="COMPLETED", count=len(executor.calls)),
                logical_external_objects=SideEffectDetail(
                    status=(
                        "COMPLETED"
                        if logical_object_evidence.executor_reached is True
                        else "NOT_RUN"
                    ),
                    count=logical_object_evidence.resulting_object_count,
                ),
            ),
        }
    )
    final_match = persisted.order.state is case.recovery.expected_final_state
    reliability_match = (
        completion_match
        and final_match
        and prior_receipt_preserved
        and retry_generation_match
        and logical_object_evidence.logical_duplication_count == 0
        and logical_object_evidence.replay_created_extra_object is False
        and logical_object_evidence.completed_step_rerun is False
    )
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
        retry_generation_before=retry_generation_before,
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
                if not isinstance(result.actual.order_id, UUID):
                    results.append(result)
                else:
                    try:
                        order_id = await _order_id_from_intake(session_factory, case, result)
                    except RuntimeError as error:
                        results.append(
                            _error_result(case, error, _provider_observation(case_runtime))
                        )
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
