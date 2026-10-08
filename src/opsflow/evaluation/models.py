"""Strict, JSON-safe contracts for the Phase 11 evaluation corpus and results."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StrictBool,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from opsflow.application.orders import CreateOrderDisposition
from opsflow.domain.order import OrderState
from opsflow.domain.records import SourceDocumentType, ValidationSeverity
from opsflow.extraction.models import ExtractionDraft
from opsflow.orchestration.contracts import IntakeExecution
from opsflow.order_sync.contracts import OrderSyncFailureCode
from opsflow.review.contracts import OperatorRole
from opsflow.validation.models import (
    ApprovalLevel,
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
    ValidationFacts,
    ValidationRoute,
)

type CanonicalValue = str | Decimal | date | None
type SafeFailureCode = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]
type SafeIdentifier = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
type BoundedReason = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=512),
]

_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_CASE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.ASCII)
_SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+", re.ASCII)


class ContractModel(BaseModel):
    """Base for closed result/manifest objects with immutable parsed values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationMode(StrEnum):
    PROVIDER_FREE = "provider_free"
    LIVE_GEMINI = "live_gemini"


class CaseCategory(StrEnum):
    NORMAL = "normal"
    EDGE = "edge"
    SECURITY = "security"
    DETERMINISTIC_VIOLATION = "deterministic_violation"
    DUPLICATE = "duplicate"
    RETRY_RECOVERY = "retry_recovery"


class CaseResultStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class ExtractionQualityStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    AVAILABLE = "AVAILABLE"


def _nonblank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("blank strings must be represented as null")
    return value


def _required_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must be a non-blank string")
    return value


def _safe_reason(value: str | None) -> str | None:
    if value is None:
        return None
    lowered = value.lower()
    forbidden_markers = (
        "\n",
        "\r",
        "bearer ",
        "api_key",
        "authorization",
        "traceback",
        "database_url",
        "postgresql://",
    )
    if any(marker in lowered for marker in forbidden_markers):
        raise ValueError("result reasons must be sanitized human-readable summaries")
    return value


class SourceSpec(ContractModel):
    """Human-readable source identity in the corpus manifest."""

    path: StrictStr
    document_type: SourceDocumentType
    mime_type: StrictStr
    sha256: StrictStr

    _path_nonblank = field_validator("path")(_required_nonblank)
    _mime_nonblank = field_validator("mime_type")(_required_nonblank)

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        from pathlib import PurePosixPath

        if "\\" in value or "\x00" in value:
            raise ValueError("source.path must use safe relative POSIX path syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("source.path must be relative and must not traverse parents")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha256_format(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("sha256 must be a lowercase 64-character SHA-256 digest")
        return value

    @model_validator(mode="after")
    def _supported_mime_pair(self) -> SourceSpec:
        expected = {
            SourceDocumentType.EMAIL_BODY: "text/plain",
            SourceDocumentType.CSV: "text/csv",
            SourceDocumentType.XLSX: (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            SourceDocumentType.PDF: "application/pdf",
        }
        if self.document_type not in expected:
            raise ValueError("document_type is not supported by the evaluation corpus")
        if self.mime_type != expected[self.document_type]:
            raise ValueError("source document_type and MIME type do not match")
        return self


class ExpectedLine(ContractModel):
    """Named, human-authored expected values for one ordered line."""

    sku: StrictStr | None
    description: StrictStr | None
    quantity: Decimal | None
    submitted_price: Decimal | None

    _optional_strings = field_validator("sku", "description")(_nonblank)


class ExpectedExtraction(ContractModel):
    """Named manifest ground truth, kept separate from scoring projections."""

    customer_name: StrictStr | None
    customer_reference: StrictStr | None
    po_number: StrictStr | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: StrictStr | None
    notes: StrictStr | None
    lines: tuple[ExpectedLine, ...]

    _optional_strings = field_validator(
        "customer_name",
        "customer_reference",
        "po_number",
        "currency",
        "notes",
    )(_nonblank)


class TrustedBusinessDataExpectation(ContractModel):
    """Manifest reference to synthetic lookup data and OpsFlow-local facts."""

    fixture_path: StrictStr
    facts: ValidationFacts

    _fixture_nonblank = field_validator("fixture_path")(_required_nonblank)

    @field_validator("fixture_path")
    @classmethod
    def _fixture_path_is_relative(cls, value: str) -> str:
        from pathlib import PurePosixPath

        if "\\" in value or "\x00" in value:
            raise ValueError("trusted fixture path must use safe relative POSIX syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("trusted fixture path must be relative and must not traverse parents")
        return value


class BenchmarkValidationContext(ContractModel):
    """Pinned deterministic policy inputs carried by corpus v1."""

    evaluation_date: date
    supported_currencies: tuple[StrictStr, ...]
    price_tolerance_fraction: Decimal
    high_value_threshold: Decimal

    @field_validator("supported_currencies")
    @classmethod
    def _supported_currencies_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(
            re.fullmatch(r"[A-Z]{3}", item, flags=re.ASCII) is None for item in value
        ):
            raise ValueError("supported_currencies must contain uppercase ISO currency codes")
        if len(value) != len(set(value)):
            raise ValueError("supported_currencies must be unique")
        return value

    @field_validator("price_tolerance_fraction", "high_value_threshold")
    @classmethod
    def _finite_nonnegative_decimal(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("benchmark decimal policy values must be finite and non-negative")
        return value


_VALIDATION_ISSUE_CODES = frozenset(
    {
        "AMBIGUOUS_CUSTOMER",
        "CATALOGUE_PRICE_UNAVAILABLE",
        "CURRENCY_REQUIRED",
        "CUSTOMER_REQUIRED",
        "DELIVERY_BEFORE_ORDER_DATE",
        "DELIVERY_DATE_IN_PAST",
        "DELIVERY_DATE_REQUIRED",
        "DOCUMENT_ALREADY_PROCESSED",
        "DUPLICATE_CUSTOMER_PO",
        "HIGH_VALUE_APPROVAL_REQUIRED",
        "INACTIVE_CUSTOMER",
        "INACTIVE_SKU",
        "INSUFFICIENT_INVENTORY",
        "INVENTORY_UNAVAILABLE",
        "ORDER_DATE_IN_FUTURE",
        "ORDER_DATE_REQUIRED",
        "ORDER_LINES_REQUIRED",
        "PO_NUMBER_REQUIRED",
        "PRICE_OUTSIDE_TOLERANCE",
        "PRODUCT_CURRENCY_MISMATCH",
        "QUANTITY_NOT_POSITIVE",
        "QUANTITY_REQUIRED",
        "SKU_REQUIRED",
        "SUBMITTED_PRICE_NEGATIVE",
        "SUBMITTED_PRICE_REQUIRED",
        "UNKNOWN_CUSTOMER",
        "UNKNOWN_SKU",
        "UNSUPPORTED_CURRENCY",
    }
)


class ExpectedValidation(ContractModel):
    """Expected deterministic validation result for cases that run validation."""

    route: ValidationRoute
    approval_level: ApprovalLevel | None
    issue_codes: tuple[StrictStr, ...]
    issue_severities: dict[StrictStr, ValidationSeverity]
    pre_approval_state: OrderState
    external_execution_eligible: StrictBool

    @model_validator(mode="after")
    def _issue_severity_keys_match(self) -> ExpectedValidation:
        if set(self.issue_codes) != set(self.issue_severities):
            raise ValueError("issue_codes and issue_severities must describe the same facts")
        unknown_codes = set(self.issue_codes) - _VALIDATION_ISSUE_CODES
        if unknown_codes:
            raise ValueError("issue_codes contains an unsupported deterministic rule code")
        return self


class ApprovalScenario(ContractModel):
    """Manifest-directed human approval expectation."""

    role: OperatorRole
    action: Literal["APPROVE"]
    expected_state: OrderState = OrderState.APPROVED

    @model_validator(mode="after")
    def _bounded_approval_action(self) -> ApprovalScenario:
        if self.expected_state is not OrderState.APPROVED:
            raise ValueError("approval scenarios must end in APPROVED state")
        return self


class ReplayScenario(ContractModel):
    """Bounded duplicate/replay expectation, present only on duplicate cases."""

    duplicate_group_id: StrictStr
    seed_case_id: StrictStr
    replay_attempt_count: Annotated[int, Field(strict=True, ge=1, le=10)]
    expected_creation_disposition: CreateOrderDisposition
    expected_intake_execution: IntakeExecution

    _nonblank_ids = field_validator("duplicate_group_id", "seed_case_id")(_required_nonblank)

    @model_validator(mode="after")
    def _current_duplicate_contract(self) -> ReplayScenario:
        if self.expected_creation_disposition is not CreateOrderDisposition.REPLAYED_EXISTING:
            raise ValueError("duplicate replay creation disposition must be REPLAYED_EXISTING")
        if self.expected_intake_execution is not IntakeExecution.STANDING_DOWN:
            raise ValueError("duplicate replay intake execution must be STANDING_DOWN")
        return self


class RecoveryScenario(ContractModel):
    """Bounded retry/recovery expectation, present only on retry cases."""

    injected_stage: OrderState
    failure_code: SafeFailureCode
    expected_resume_origin: OrderState
    expected_durable_outcome: OrderState
    expected_final_state: OrderState
    preserve_prior_receipts: StrictBool

    @model_validator(mode="after")
    def _real_retryable_failure(self) -> RecoveryScenario:
        valid_origins = {
            OrderState.PROCESSING,
            OrderState.EXTRACTED,
            OrderState.SYNCING,
        }
        if self.injected_stage not in valid_origins:
            raise ValueError("recovery injected stage must be a durable retry origin")
        if self.injected_stage is not self.expected_resume_origin:
            raise ValueError("recovery resume origin must match the injected durable stage")
        if self.expected_durable_outcome is not OrderState.FAILED_RETRYABLE:
            raise ValueError("recovery outcome must be FAILED_RETRYABLE")
        allowed_by_stage = {
            OrderState.PROCESSING: frozenset({"PROVIDER_UNAVAILABLE"}),
            OrderState.EXTRACTED: frozenset({"BUSINESS_DATA_PROVIDER_ERROR"}),
            OrderState.SYNCING: frozenset({OrderSyncFailureCode.WORKER_LEASE_EXHAUSTED.value}),
        }
        if self.failure_code not in allowed_by_stage[self.injected_stage]:
            raise ValueError("recovery failure code is not valid for the injected stage")
        return self


class CorpusCase(ContractModel):
    """One manifest case with conditional scenario sections."""

    case_id: StrictStr
    primary_category: CaseCategory
    tags: tuple[StrictStr, ...]
    source: SourceSpec
    expected_extraction: ExpectedExtraction | None = None
    trusted_business_data: TrustedBusinessDataExpectation | None = None
    expected_validation: ExpectedValidation | None = None
    approval: ApprovalScenario | None = None
    replay: ReplayScenario | None = None
    recovery: RecoveryScenario | None = None

    @field_validator("case_id")
    @classmethod
    def _case_id_format(cls, value: str) -> str:
        if _CASE_ID.fullmatch(value) is None:
            raise ValueError("case_id must be lowercase ASCII with hyphen separators")
        return value

    @field_validator("tags")
    @classmethod
    def _tags_nonblank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not tag.strip() for tag in value):
            raise ValueError("tags must contain non-blank values")
        return value

    @model_validator(mode="after")
    def _conditional_sections(self) -> CorpusCase:
        parser_only = "parser_only" in self.tags or "failure" in self.tags
        if self.expected_extraction is None and not parser_only:
            raise ValueError("expected_extraction is required for extraction cases")

        validation_tag = "validation" in self.tags
        if (self.expected_validation is None) != (self.trusted_business_data is None):
            raise ValueError(
                "expected_validation and trusted_business_data must be present together"
            )
        if validation_tag and self.expected_validation is None:
            raise ValueError("validation cases require expected_validation and trusted data")

        if self.approval is not None and "approval" not in self.tags:
            raise ValueError("approval is allowed only for approval-tagged cases")
        if "approval" in self.tags and self.approval is None:
            raise ValueError("approval-tagged cases require an approval scenario")
        if self.expected_validation is not None:
            if self.expected_validation.external_execution_eligible and self.approval is None:
                raise ValueError("external execution eligibility requires an approval scenario")
            if self.approval is not None and (
                self.expected_validation.route is not ValidationRoute.READY_FOR_APPROVAL
                or self.expected_validation.pre_approval_state is not OrderState.READY_FOR_APPROVAL
                or self.expected_validation.external_execution_eligible is not True
            ):
                raise ValueError("approval scenarios require READY_FOR_APPROVAL validation truth")
            if self.approval is not None:
                allowed_roles = {
                    ApprovalLevel.STANDARD: frozenset(
                        {OperatorRole.APPROVER, OperatorRole.ELEVATED_APPROVER}
                    ),
                    ApprovalLevel.ELEVATED: frozenset({OperatorRole.ELEVATED_APPROVER}),
                }
                approval_level = self.expected_validation.approval_level
                if (
                    approval_level is None
                    or self.approval.role not in allowed_roles[approval_level]
                ):
                    raise ValueError("approval role is not authorized for the approval level")
        elif self.approval is not None:
            raise ValueError("approval scenarios require expected validation truth")

        if self.primary_category is CaseCategory.DUPLICATE:
            if self.replay is None:
                raise ValueError("duplicate cases require a replay scenario")
        elif self.replay is not None:
            raise ValueError("replay is allowed only for duplicate cases")

        if self.primary_category is CaseCategory.RETRY_RECOVERY:
            if self.recovery is None:
                raise ValueError("retry_recovery cases require a recovery scenario")
        elif self.recovery is not None:
            raise ValueError("recovery is allowed only for retry_recovery cases")

        if self.recovery is not None:
            if (
                self.recovery.injected_stage
                in {
                    OrderState.PROCESSING,
                    OrderState.EXTRACTED,
                }
                and self.approval is None
            ):
                if self.expected_validation is None:
                    raise ValueError(
                        "intake recovery without approval requires expected validation truth"
                    )
                if self.expected_validation.external_execution_eligible:
                    raise ValueError(
                        "intake recovery without approval cannot be externally executable"
                    )
                if (
                    self.recovery.expected_final_state
                    is not self.expected_validation.pre_approval_state
                ):
                    raise ValueError(
                        "intake recovery without approval must end at "
                        "the expected pre-approval state"
                    )
            if self.recovery.injected_stage is OrderState.SYNCING and self.approval is None:
                raise ValueError("SYNCING recovery requires an explicit approval scenario")
        return self


class CorpusManifest(ContractModel):
    """Versioned ordered manifest identity for one synthetic corpus."""

    schema_version: Literal["opsflow-evaluation-corpus/v1"]
    corpus_version: StrictStr
    benchmark_context: BenchmarkValidationContext
    cases: tuple[CorpusCase, ...]
    trusted_catalog_path: StrictStr = "trusted-data/catalog.json"

    @field_validator("corpus_version")
    @classmethod
    def _corpus_version_format(cls, value: str) -> str:
        if _SEMVER.fullmatch(value) is None:
            raise ValueError("corpus_version must be a semantic version")
        return value

    @field_validator("trusted_catalog_path")
    @classmethod
    def _trusted_catalog_path_is_relative(cls, value: str) -> str:
        from pathlib import PurePosixPath

        if "\\" in value or "\x00" in value:
            raise ValueError("trusted catalog path must use safe relative POSIX syntax")
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise ValueError("trusted catalog path must be relative and must not traverse parents")
        return value

    @model_validator(mode="after")
    def _unique_case_ids(self) -> CorpusManifest:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id values must be unique within a manifest")
        case_by_id = {case.case_id: case for case in self.cases}
        replay_groups: set[str] = set()
        for case in self.cases:
            if case.replay is None:
                continue
            if case.replay.duplicate_group_id in replay_groups:
                raise ValueError("duplicate_group_id values must be unique within a manifest")
            replay_groups.add(case.replay.duplicate_group_id)
            seed = case_by_id.get(case.replay.seed_case_id)
            if seed is None or seed.primary_category is not CaseCategory.DUPLICATE:
                raise ValueError("replay seed_case_id must reference a duplicate manifest case")
            if seed.source.sha256 != case.source.sha256:
                raise ValueError("replay seed and case must share the same source identity")
        return self


class TrustedCatalog(ContractModel):
    """Synthetic reference catalog, not an expected-answer lookup table."""

    customers: tuple[TrustedCustomer, ...]
    products: tuple[TrustedProduct, ...]

    @model_validator(mode="after")
    def _unique_reference_records(self) -> TrustedCatalog:
        customer_refs = [customer.reference for customer in self.customers]
        if len(customer_refs) != len(set(customer_refs)):
            raise ValueError("trusted customer references must be unique")
        product_skus = [product.sku for product in self.products]
        if len(product_skus) != len(set(product_skus)):
            raise ValueError("trusted product SKUs must be unique")
        return self


class FieldCounts(ContractModel):
    tp: NonNegativeInt = 0
    fp: NonNegativeInt = 0
    fn: NonNegativeInt = 0


class RateMetric(ContractModel):
    numerator: NonNegativeInt
    denominator: NonNegativeInt
    value: Decimal | None

    @model_validator(mode="after")
    def _undefined_rate_is_null(self) -> RateMetric:
        if self.numerator > self.denominator:
            raise ValueError("rate numerator must not exceed denominator")
        if self.denominator == 0 and self.numerator != 0:
            raise ValueError("zero-denominator rates must have a zero numerator")
        if self.denominator == 0 and self.value is not None:
            raise ValueError("undefined rates must have a null value")
        if self.value is not None and (
            not self.value.is_finite() or self.value < 0 or self.value > 1
        ):
            raise ValueError("rate values must be between zero and one")
        return self


class FieldMetric(ContractModel):
    field_name: StrictStr
    counts: FieldCounts
    precision: RateMetric
    recall: RateMetric
    f1: RateMetric


class ExtractionQuality(ContractModel):
    """Mode-scoped extraction quality; provider-free values are unavailable."""

    status: ExtractionQualityStatus
    complete_exact_match: RateMetric | None = None
    field_tp: NonNegativeInt | None = None
    field_fp: NonNegativeInt | None = None
    field_fn: NonNegativeInt | None = None
    field_micro_precision: RateMetric | None = None
    field_micro_recall: RateMetric | None = None
    field_micro_f1: RateMetric | None = None
    per_field: tuple[FieldMetric, ...] | None = None
    reached_live_gemini_case_count: NonNegativeInt = 0
    reached_live_gemini_case_ids: tuple[StrictStr, ...] = ()
    reason: BoundedReason

    _safe_reason_text = field_validator("reason")(_safe_reason)

    @property
    def precision(self) -> RateMetric | None:
        return self.field_micro_precision

    @property
    def recall(self) -> RateMetric | None:
        return self.field_micro_recall

    @property
    def f1(self) -> RateMetric | None:
        return self.field_micro_f1

    @model_validator(mode="after")
    def _mode_scoped_quality(self) -> ExtractionQuality:
        quality_fields = (
            self.complete_exact_match,
            self.field_tp,
            self.field_fp,
            self.field_fn,
            self.field_micro_precision,
            self.field_micro_recall,
            self.field_micro_f1,
            self.per_field,
        )
        if self.status is ExtractionQualityStatus.NOT_APPLICABLE:
            if any(value is not None for value in quality_fields):
                raise ValueError("NOT_APPLICABLE extraction quality must contain null metrics")
            if "no real model" not in self.reason.lower():
                raise ValueError("NOT_APPLICABLE quality must explain that no real model ran")
        return self


class ContractEvidence(ContractModel):
    """Deterministic provider-free evidence, deliberately not accuracy."""

    provider_schema_accepted: StrictBool | None = None
    parser_succeeded: StrictBool | None = None
    evidence_grounded: StrictBool | None = None
    source_identity_matches: StrictBool | None = None
    extraction_persistence_round_trip: StrictBool | None = None
    scripted_provider_call_count: NonNegativeInt | None = None
    scorer_self_test: StrictBool | None = None


class CaseActual(ContractModel):
    """Sanitized per-case actuals; source and provider payloads are excluded."""

    parse: CaseResultStatus | None = None
    extraction_contract: CaseResultStatus | None = None
    route: ValidationRoute | None = None
    approval_level: ApprovalLevel | None = None
    pre_approval_state: OrderState | None = None
    issue_facts: tuple[tuple[SafeFailureCode, ValidationSeverity], ...] = ()
    idempotent_replay: StrictBool | None = None
    creation_disposition: CreateOrderDisposition | None = None
    intake_execution: IntakeExecution | None = None
    external_execution: SafeFailureCode | None = None
    external_execution_eligible: StrictBool | None = None
    failure_code: SafeFailureCode | None = None


class CaseScores(ContractModel):
    """Stable home for per-case scores added by later milestones."""

    extraction_exact_match: StrictBool | None = None
    validation_match: StrictBool | None = None


class DurationSummary(ContractModel):
    """Named duration extension points; absent measurements remain null."""

    parse_ms: Decimal | None = None
    deterministic_validation_ms: Decimal | None = None
    provider_free_intake_ms: Decimal | None = None
    live_gemini_call_ms: Decimal | None = None

    @field_validator(
        "parse_ms",
        "deterministic_validation_ms",
        "provider_free_intake_ms",
        "live_gemini_call_ms",
    )
    @classmethod
    def _finite_nonnegative_duration(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("duration milliseconds must be finite and non-negative")
        return value


class ProviderSummary(ContractModel):
    """Sanitized provider reachability and authoritative usage placeholders."""

    name: Literal["fake", "gemini"] | None = None
    calls: NonNegativeInt = 0
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    total_tokens: NonNegativeInt | None = None


class SideEffectDetail(ContractModel):
    """Bounded side-effect summary without response bodies or credentials."""

    status: SafeFailureCode | None = None
    count: NonNegativeInt | None = None


class SideEffectSummary(ContractModel):
    notification: SideEffectDetail = Field(default_factory=SideEffectDetail)
    order_sync: SideEffectDetail = Field(default_factory=SideEffectDetail)
    logical_external_objects: SideEffectDetail = Field(default_factory=SideEffectDetail)


class CaseResult(ContractModel):
    """Stable nested per-case result shape with internal scoring inputs excluded."""

    case_id: SafeIdentifier
    status: CaseResultStatus
    actual: CaseActual = Field(default_factory=CaseActual)
    scores: CaseScores = Field(default_factory=CaseScores)
    durations_ms: DurationSummary = Field(default_factory=DurationSummary)
    provider: ProviderSummary = Field(default_factory=ProviderSummary)
    side_effects: SideEffectSummary = Field(default_factory=SideEffectSummary)
    expected_extraction: ExpectedExtraction | None = Field(default=None, exclude=True)
    predicted_extraction: ExtractionDraft | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _error_has_sanitized_failure_code(self) -> CaseResult:
        if self.status is CaseResultStatus.ERROR and self.actual.failure_code is None:
            raise ValueError("ERROR cases require a bounded failure_code")
        if self.status is not CaseResultStatus.ERROR and self.actual.failure_code is not None:
            raise ValueError("failure_code is only valid for ERROR cases")
        if self.provider.calls == 0 and self.provider.name is not None:
            raise ValueError("provider name requires at least one provider call")
        return self

    @property
    def provider_reached(self) -> bool:
        return self.provider.calls > 0

    @property
    def provider_name(self) -> str | None:
        return self.provider.name

    @property
    def provider_call_count(self) -> int:
        return self.provider.calls

    @property
    def failure_code(self) -> str | None:
        return self.actual.failure_code

    @property
    def validation_route(self) -> ValidationRoute | None:
        return self.actual.route

    @property
    def approval_level(self) -> ApprovalLevel | None:
        return self.actual.approval_level

    @property
    def pre_approval_state(self) -> OrderState | None:
        return self.actual.pre_approval_state

    @property
    def issue_facts(self) -> tuple[tuple[str, ValidationSeverity], ...]:
        return self.actual.issue_facts


class DatabaseMetadata(ContractModel):
    engine: StrictStr
    isolated: StrictBool


class RunMetadata(ContractModel):
    """Stable run identity and allowlisted environment metadata."""

    run_id: StrictStr
    mode: EvaluationMode
    started_at_utc: datetime
    finished_at_utc: datetime
    git_sha: StrictStr
    corpus_version: StrictStr
    command: BoundedReason
    dependency_lock_identity: BoundedReason | None = None
    database_version: BoundedReason | None = None
    gemini_model: StrictStr | None = None
    python_version: StrictStr | None = None
    platform: StrictStr | None = None
    cpu_architecture: StrictStr | None = None
    database: DatabaseMetadata

    @field_validator("git_sha")
    @classmethod
    def _git_sha_format(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{40}", value, flags=re.ASCII) is None:
            raise ValueError("git_sha must be a lowercase 40-character commit SHA")
        return value

    _safe_environment_identity = field_validator(
        "command", "dependency_lock_identity", "database_version"
    )(_safe_reason)


class MetricExtension(ContractModel):
    """Closed extension point for later aggregate measurements."""

    sample_count: NonNegativeInt | None = None
    numerator: NonNegativeInt | None = None
    denominator: NonNegativeInt | None = None
    value: Decimal | None = None


class CostMetrics(ContractModel):
    status: Literal["NOT_APPLICABLE", "AVAILABLE", "ERROR"] = "NOT_APPLICABLE"
    estimated_model_cost_per_initial_order: Decimal | None = None
    initial_order_count: NonNegativeInt = 0
    gemini_called_order_count: NonNegativeInt = 0
    zero_call_order_count: NonNegativeInt = 0
    complete_usage_order_count: NonNegativeInt = 0
    incomplete_usage_order_count: NonNegativeInt = 0
    incomplete_usage_call_count: NonNegativeInt = 0
    missing_call_attribution_count: NonNegativeInt = 0
    missing_input_token_count: NonNegativeInt = 0
    missing_output_token_count: NonNegativeInt = 0
    missing_total_token_count: NonNegativeInt = 0
    missing_pricing_snapshot_count: NonNegativeInt = 0


class MetricsBundle(ContractModel):
    extraction_quality: ExtractionQuality
    extraction_contract: ContractEvidence = Field(default_factory=ContractEvidence)
    routing: MetricExtension = Field(default_factory=MetricExtension)
    safety: MetricExtension = Field(default_factory=MetricExtension)
    latency: MetricExtension = Field(default_factory=MetricExtension)
    provider_usage: MetricExtension = Field(default_factory=MetricExtension)
    cost: CostMetrics = Field(default_factory=CostMetrics)


class PricingStatus(ContractModel):
    pricing_snapshot_id: StrictStr | None = None
    model: StrictStr | None = None
    status: Literal["NOT_APPLICABLE", "AVAILABLE", "ERROR"]
    reason: BoundedReason | None = None

    _safe_reason_text = field_validator("reason")(_safe_reason)


class CorpusComposition(ContractModel):
    case_count: NonNegativeInt
    primary_category_counts: dict[CaseCategory, NonNegativeInt]
    format_counts: dict[SourceDocumentType, NonNegativeInt]
    tag_counts: dict[StrictStr, NonNegativeInt]


class ReleaseGateResult(ContractModel):
    gate_id: SafeFailureCode
    numerator: NonNegativeInt | None = None
    denominator: NonNegativeInt | None = None
    failing_case_ids: tuple[StrictStr, ...] = ()
    status: Literal["PASS", "FAIL", "ERROR"]


class ReleaseGateSummary(ContractModel):
    all_passed: StrictBool | None = None
    results: tuple[ReleaseGateResult, ...] = ()


class EvaluationRunResult(ContractModel):
    """Stable Section 10.1 result contract for M11B–M11D."""

    schema_version: Literal["opsflow-evaluation-result/v1"] = "opsflow-evaluation-result/v1"
    evaluation_version: Literal["phase11-v1"] = "phase11-v1"
    run: RunMetadata
    corpus: CorpusComposition
    cases: tuple[CaseResult, ...]
    metrics: MetricsBundle
    pricing: PricingStatus
    release_gates: ReleaseGateSummary
    limitations: tuple[BoundedReason, ...] = ()

    @field_validator("limitations")
    @classmethod
    def _safe_limitation_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _safe_reason(value)
        return values

    @model_validator(mode="after")
    def _provider_free_quality(self) -> EvaluationRunResult:
        if self.run.mode is EvaluationMode.PROVIDER_FREE:
            if self.metrics.extraction_quality.status is not ExtractionQualityStatus.NOT_APPLICABLE:
                raise ValueError("provider-free results require NOT_APPLICABLE extraction quality")
            if self.run.gemini_model is not None:
                raise ValueError("provider-free results cannot identify a Gemini model")
            if any(case.provider.name == "gemini" for case in self.cases):
                raise ValueError("provider-free results cannot contain Gemini provider evidence")
            if (
                self.pricing.status != "NOT_APPLICABLE"
                or self.pricing.pricing_snapshot_id is not None
                or self.pricing.model is not None
            ):
                raise ValueError("provider-free results cannot contain live pricing evidence")
            cost = self.metrics.cost
            if (
                cost.status != "NOT_APPLICABLE"
                or cost.estimated_model_cost_per_initial_order is not None
                or cost.gemini_called_order_count != 0
            ):
                raise ValueError("provider-free results cannot contain Gemini cost evidence")
        if self.run.mode is EvaluationMode.LIVE_GEMINI:
            for case in self.cases:
                if case.provider.name == "fake" and case.provider.calls > 0:
                    raise ValueError("live_gemini results cannot contain fake provider calls")
        return self


__all__ = [
    "ApprovalLevel",
    "ApprovalScenario",
    "BenchmarkValidationContext",
    "BusinessDataLookupRequest",
    "CanonicalValue",
    "CaseActual",
    "CaseCategory",
    "CaseResult",
    "CaseResultStatus",
    "CaseScores",
    "ContractEvidence",
    "CorpusCase",
    "CorpusComposition",
    "CorpusManifest",
    "CostMetrics",
    "DatabaseMetadata",
    "DurationSummary",
    "EvaluationMode",
    "EvaluationRunResult",
    "ExpectedExtraction",
    "ExpectedLine",
    "ExpectedValidation",
    "ExtractionQuality",
    "ExtractionQualityStatus",
    "FieldCounts",
    "FieldMetric",
    "MetricsBundle",
    "OrderState",
    "PricingStatus",
    "ProviderSummary",
    "RateMetric",
    "RecoveryScenario",
    "ReplayScenario",
    "ReleaseGateResult",
    "ReleaseGateSummary",
    "RunMetadata",
    "SafeFailureCode",
    "SideEffectSummary",
    "SourceDocumentType",
    "SourceSpec",
    "TrustedBusinessData",
    "TrustedBusinessDataExpectation",
    "TrustedCatalog",
    "TrustedCustomer",
    "TrustedProduct",
    "ValidationFacts",
    "ValidationRoute",
    "ValidationSeverity",
]
