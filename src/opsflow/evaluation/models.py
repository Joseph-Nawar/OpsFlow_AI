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
    field_validator,
    model_validator,
)

from opsflow.domain.order import OrderState
from opsflow.domain.records import SourceDocumentType, ValidationSeverity
from opsflow.extraction.models import ExtractionDraft
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
    SUCCEEDED = "PASS"
    FAILED = "FAIL"
    SKIPPED = "SKIPPED"


class ExtractionQualityStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    AVAILABLE = "AVAILABLE"


class ReplayDisposition(StrEnum):
    REPLAYED_EXISTING = "REPLAYED_EXISTING"
    STAND_DOWN = "STANDING_DOWN"


def _nonblank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("blank strings must be represented as null")
    return value


def _required_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must be a non-blank string")
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
        if len(self.issue_codes) != len(set(self.issue_codes)):
            raise ValueError("issue_codes must not contain duplicate rule codes")
        return self


class ApprovalScenario(ContractModel):
    """Manifest-directed human approval expectation."""

    role: StrictStr
    action: StrictStr
    expected_state: Literal[OrderState.APPROVED] = OrderState.APPROVED

    _nonblank_role_action = field_validator("role", "action")(_required_nonblank)


class ReplayScenario(ContractModel):
    """Bounded duplicate/replay expectation, present only on duplicate cases."""

    duplicate_group_id: StrictStr
    seed_case_id: StrictStr
    replay_attempt_count: Annotated[int, Field(strict=True, ge=1, le=10)]
    expected_disposition: ReplayDisposition

    _nonblank_ids = field_validator("duplicate_group_id", "seed_case_id")(_required_nonblank)


class RecoveryScenario(ContractModel):
    """Bounded retry/recovery expectation, present only on retry cases."""

    injected_stage: StrictStr
    failure_code: StrictStr
    expected_resume_origin: OrderState
    expected_durable_outcome: StrictStr
    expected_final_state: OrderState
    preserve_prior_receipts: StrictBool

    _nonblank_values = field_validator(
        "injected_stage", "failure_code", "expected_durable_outcome"
    )(_required_nonblank)


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
        return self


class CorpusManifest(ContractModel):
    """Versioned ordered manifest identity for one synthetic corpus."""

    schema_version: Literal["opsflow-evaluation-corpus/v1"]
    corpus_version: StrictStr
    cases: tuple[CorpusCase, ...]
    trusted_catalog_path: StrictStr = "trusted-data/catalog.json"

    @field_validator("corpus_version")
    @classmethod
    def _corpus_version_format(cls, value: str) -> str:
        if _SEMVER.fullmatch(value) is None:
            raise ValueError("corpus_version must be a semantic version")
        return value

    @model_validator(mode="after")
    def _unique_case_ids(self) -> CorpusManifest:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id values must be unique within a manifest")
        return self


class TrustedCatalog(ContractModel):
    """Synthetic reference catalog, not an expected-answer lookup table."""

    customers: tuple[TrustedCustomer, ...]
    products: tuple[TrustedProduct, ...]


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
        if self.denominator == 0 and self.value is not None:
            raise ValueError("undefined rates must have a null value")
        if self.denominator > 0 and self.value is None:
            raise ValueError("defined rates must have a numeric value")
        if self.value is not None and (self.value < 0 or self.value > 1):
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
    precision: RateMetric | None = None
    recall: RateMetric | None = None
    f1: RateMetric | None = None
    per_field: tuple[FieldMetric, ...] | None = None
    reached_live_gemini_case_count: NonNegativeInt = 0
    reached_live_gemini_case_ids: tuple[StrictStr, ...] = ()
    reason: StrictStr

    @field_validator("reason")
    @classmethod
    def _reason_nonblank(cls, value: str) -> str:
        return _required_nonblank(value)

    @model_validator(mode="after")
    def _mode_scoped_quality(self) -> ExtractionQuality:
        quality_fields = (
            self.complete_exact_match,
            self.field_tp,
            self.field_fp,
            self.field_fn,
            self.precision,
            self.recall,
            self.f1,
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


class CaseResult(ContractModel):
    """Sanitized actuals for one case; raw source material is not a result field."""

    case_id: StrictStr
    status: CaseResultStatus
    provider_reached: StrictBool
    failure_code: StrictStr | None = None
    validation_route: ValidationRoute | None = None
    approval_level: ApprovalLevel | None = None
    pre_approval_state: OrderState | None = None
    issue_facts: tuple[tuple[StrictStr, ValidationSeverity], ...] = ()
    replay_disposition: ReplayDisposition | None = None
    external_execution_eligible: StrictBool | None = None
    contract_evidence: ContractEvidence | None = None
    predicted_extraction: ExtractionDraft | None = Field(default=None, exclude=True)

    _failure_nonblank = field_validator("failure_code")(_nonblank)

    @model_validator(mode="after")
    def _status_failure_pair(self) -> CaseResult:
        if self.status is CaseResultStatus.FAILED and self.failure_code is None:
            raise ValueError("failed cases require a bounded failure_code")
        if self.status is not CaseResultStatus.FAILED and self.failure_code is not None:
            raise ValueError("failure_code is only valid for failed cases")
        return self


class EnvironmentMetadata(ContractModel):
    """Allowlisted run metadata; arbitrary or secret-bearing metadata is forbidden."""

    gemini_model: StrictStr | None = None
    python_version: StrictStr | None = None
    platform: StrictStr | None = None
    cpu_architecture: StrictStr | None = None
    database_engine: StrictStr | None = None
    database_version: StrictStr | None = None
    database_isolated: StrictBool | None = None


class CorpusComposition(ContractModel):
    case_count: NonNegativeInt
    primary_category_counts: dict[CaseCategory, NonNegativeInt]
    format_counts: dict[SourceDocumentType, NonNegativeInt]
    tag_counts: dict[StrictStr, NonNegativeInt]


class ReleaseGateResult(ContractModel):
    name: StrictStr
    passed: StrictBool
    reason: StrictStr | None = None


class EvaluationRunResult(ContractModel):
    """Initial versioned result contract, before later artifact/report tasks."""

    schema_version: Literal["opsflow-evaluation-result/v1"] = "opsflow-evaluation-result/v1"
    evaluation_version: Literal["phase11-v1"] = "phase11-v1"
    run_id: StrictStr
    started_at: datetime
    finished_at: datetime
    git_sha: StrictStr
    corpus_version: StrictStr
    result_schema_version: StrictStr
    mode: EvaluationMode
    command: StrictStr
    environment: EnvironmentMetadata = EnvironmentMetadata()
    corpus: CorpusComposition | None = None
    cases: tuple[CaseResult, ...]
    extraction_quality: ExtractionQuality
    release_gates: tuple[ReleaseGateResult, ...] = ()
    limitations: tuple[StrictStr, ...] = ()

    @field_validator("git_sha")
    @classmethod
    def _git_sha_format(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{40}", value, flags=re.ASCII) is None:
            raise ValueError("git_sha must be a lowercase 40-character commit SHA")
        return value

    @model_validator(mode="after")
    def _provider_free_quality(self) -> EvaluationRunResult:
        if (
            self.mode is EvaluationMode.PROVIDER_FREE
            and self.extraction_quality.status is not ExtractionQualityStatus.NOT_APPLICABLE
        ):
            raise ValueError("provider-free results require NOT_APPLICABLE extraction quality")
        return self


__all__ = [
    "ApprovalLevel",
    "ApprovalScenario",
    "BusinessDataLookupRequest",
    "CanonicalValue",
    "CaseCategory",
    "CaseResult",
    "CaseResultStatus",
    "ContractEvidence",
    "CorpusCase",
    "CorpusComposition",
    "CorpusManifest",
    "EnvironmentMetadata",
    "EvaluationMode",
    "EvaluationRunResult",
    "ExpectedExtraction",
    "ExpectedLine",
    "ExpectedValidation",
    "ExtractionQuality",
    "ExtractionQualityStatus",
    "FieldCounts",
    "FieldMetric",
    "OrderState",
    "RateMetric",
    "RecoveryScenario",
    "ReplayDisposition",
    "ReplayScenario",
    "ReleaseGateResult",
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
