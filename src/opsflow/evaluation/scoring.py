"""Pure canonicalization and scoring for Phase 11 extraction contracts."""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from opsflow.domain.order import OrderState
from opsflow.domain.records import ValidationSeverity
from opsflow.extraction.models import ExtractionDraft

from .models import (
    ApprovalLevel,
    CanonicalValue,
    CaseResult,
    ContractModel,
    EvaluationMode,
    ExpectedExtraction,
    ExpectedValidation,
    ExtractionQuality,
    ExtractionQualityStatus,
    FieldCounts,
    FieldMetric,
    RateMetric,
    ValidationRoute,
)

_DATE_FIELDS = {"order_date", "requested_delivery_date"}
_DECIMAL_FIELDS = {"quantity", "submitted_price"}
_EXTRACTION_FIELDS = (
    "customer_name",
    "customer_reference",
    "po_number",
    "order_date",
    "requested_delivery_date",
    "currency",
    "notes",
)


@dataclass(frozen=True, slots=True)
class CanonicalFieldFact:
    path: str
    value: CanonicalValue


@dataclass(frozen=True, slots=True)
class CanonicalExtractionProjection:
    """Derived positioned field facts; never authored in the manifest."""

    facts: tuple[CanonicalFieldFact, ...]

    def as_mapping(self) -> dict[str, CanonicalValue]:
        return {fact.path: fact.value for fact in self.facts}


class PositionedExtractionScore(ContractModel):
    exact_match: bool
    total: FieldCounts
    per_field: tuple[FieldMetric, ...]
    micro_precision: RateMetric
    micro_recall: RateMetric
    micro_f1: RateMetric


class ValidationOutcomeScore(ContractModel):
    expected_route: ValidationRoute
    actual_route: ValidationRoute | None
    route_match: bool
    approval_level_applicable: bool
    expected_approval_level: ApprovalLevel | None
    actual_approval_level: ApprovalLevel | None
    approval_level_match: bool | None
    expected_pre_approval_state: OrderState
    actual_pre_approval_state: OrderState | None
    pre_approval_state_match: bool
    issue_multiset_match: bool
    missing_issue_facts: tuple[tuple[str, ValidationSeverity], ...]
    unexpected_issue_facts: tuple[tuple[str, ValidationSeverity], ...]
    overall_match: bool


def canonicalize_value(field_name: str, value: object) -> CanonicalValue:
    """Apply the locked exact canonicalization rules without fuzzy matching."""

    if value is None:
        return None
    if isinstance(value, float):
        raise TypeError("binary floating point is not allowed in evaluation values")
    if field_name in _DATE_FIELDS:
        if isinstance(value, datetime):
            raise TypeError("date fields must not contain datetimes")
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError as error:
                raise ValueError("date fields must use ISO YYYY-MM-DD") from error
        raise TypeError("date fields must be dates or ISO date strings")
    if field_name in _DECIMAL_FIELDS:
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("Decimal values must be finite")
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return Decimal(value)
        if isinstance(value, str):
            try:
                decimal_value = Decimal(value)
            except Exception as error:
                raise ValueError("numeric fields must be Decimal values") from error
            if not decimal_value.is_finite():
                raise ValueError("Decimal values must be finite")
            return decimal_value
        raise TypeError("numeric fields must use Decimal values, not binary floats")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    raise TypeError("evaluation values must be strings, Decimal values, dates, or null")


def project_extraction(
    extraction: ExtractionDraft | ExpectedExtraction,
) -> CanonicalExtractionProjection:
    """Derive the shared named-field/position projection used by the scorer."""

    if not isinstance(extraction, (ExtractionDraft, ExpectedExtraction)):
        raise TypeError("extraction must be an ExtractionDraft or ExpectedExtraction")
    facts = [
        CanonicalFieldFact(
            path=field_name,
            value=canonicalize_value(field_name, getattr(extraction, field_name)),
        )
        for field_name in _EXTRACTION_FIELDS
    ]
    for position, line in enumerate(extraction.lines):
        for field_name in ("sku", "description", "quantity", "submitted_price"):
            facts.append(
                CanonicalFieldFact(
                    path=f"lines[{position}].{field_name}",
                    value=canonicalize_value(field_name, getattr(line, field_name)),
                )
            )
    return CanonicalExtractionProjection(tuple(facts))


def _rate(numerator: int, denominator: int, *, undefined: bool = False) -> RateMetric:
    value = None
    if denominator > 0 and not undefined:
        value = Decimal(numerator) / Decimal(denominator)
    return RateMetric(numerator=numerator, denominator=denominator, value=value)


def _field_metric(field_name: str, counts: FieldCounts) -> FieldMetric:
    precision = _rate(counts.tp, counts.tp + counts.fp)
    recall = _rate(counts.tp, counts.tp + counts.fn)
    f1 = _rate(
        2 * counts.tp,
        2 * counts.tp + counts.fp + counts.fn,
        undefined=counts.tp == 0,
    )
    return FieldMetric(
        field_name=field_name,
        counts=counts,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def score_positioned_extraction(
    expected: CanonicalExtractionProjection,
    predicted: CanonicalExtractionProjection,
) -> PositionedExtractionScore:
    """Score exact field paths and ordered line positions without reordering."""

    expected_values = expected.as_mapping()
    predicted_values = predicted.as_mapping()
    paths = tuple(dict.fromkeys((*expected_values, *predicted_values)))
    counts_by_field: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    exact_match = set(expected_values) == set(predicted_values)

    for path in paths:
        expected_value = expected_values.get(path)
        predicted_value = predicted_values.get(path)
        field_name = path.rsplit(".", maxsplit=1)[-1]
        counts = counts_by_field[field_name]
        if path not in expected_values:
            exact_match = False
            if predicted_value is not None:
                counts[1] += 1
            continue
        if path not in predicted_values:
            exact_match = False
            if expected_value is not None:
                counts[2] += 1
            continue
        if expected_value != predicted_value:
            exact_match = False
            if expected_value is not None:
                counts[2] += 1
            if predicted_value is not None:
                counts[1] += 1
        elif expected_value is not None:
            counts[0] += 1

    field_metrics = tuple(
        _field_metric(field_name, FieldCounts(tp=values[0], fp=values[1], fn=values[2]))
        for field_name, values in sorted(counts_by_field.items())
    )
    total = FieldCounts(
        tp=sum(metric.counts.tp for metric in field_metrics),
        fp=sum(metric.counts.fp for metric in field_metrics),
        fn=sum(metric.counts.fn for metric in field_metrics),
    )
    return PositionedExtractionScore(
        exact_match=exact_match,
        total=total,
        per_field=field_metrics,
        micro_precision=_rate(total.tp, total.tp + total.fp),
        micro_recall=_rate(total.tp, total.tp + total.fn),
        micro_f1=_rate(
            2 * total.tp,
            2 * total.tp + total.fp + total.fn,
            undefined=total.tp == 0,
        ),
    )


def score_validation_outcome(
    expected: ExpectedValidation | None,
    actual: CaseResult,
) -> ValidationOutcomeScore | None:
    """Compare deterministic route, approval, state, and code/severity facts."""

    if expected is None:
        return None
    expected_issues = Counter(
        (code, expected.issue_severities[code]) for code in expected.issue_codes
    )
    actual_issues = Counter(actual.issue_facts)
    missing = tuple(
        sorted(
            (expected_issues - actual_issues).elements(),
            key=lambda item: (item[0], item[1].value),
        )
    )
    unexpected = tuple(
        sorted(
            (actual_issues - expected_issues).elements(),
            key=lambda item: (item[0], item[1].value),
        )
    )
    route_match = actual.validation_route is expected.route
    approval_applicable = expected.approval_level is not None
    approval_match = (
        actual.approval_level is expected.approval_level if approval_applicable else None
    )
    state_match = actual.pre_approval_state is expected.pre_approval_state
    issue_match = not missing and not unexpected
    overall = route_match and (approval_match is not False) and state_match and issue_match
    return ValidationOutcomeScore(
        expected_route=expected.route,
        actual_route=actual.validation_route,
        route_match=route_match,
        approval_level_applicable=approval_applicable,
        expected_approval_level=expected.approval_level,
        actual_approval_level=actual.approval_level,
        approval_level_match=approval_match,
        expected_pre_approval_state=expected.pre_approval_state,
        actual_pre_approval_state=actual.pre_approval_state,
        pre_approval_state_match=state_match,
        issue_multiset_match=issue_match,
        missing_issue_facts=missing,
        unexpected_issue_facts=unexpected,
        overall_match=overall,
    )


def score_extraction_quality(
    results: Sequence[CaseResult], mode: EvaluationMode
) -> ExtractionQuality:
    """Return model quality only for live cases that reached real Gemini."""

    if mode is EvaluationMode.PROVIDER_FREE:
        return ExtractionQuality(
            status=ExtractionQualityStatus.NOT_APPLICABLE,
            reason=(
                "No real model was evaluated; scripted provider output is not an "
                "extraction-quality score."
            ),
        )

    reached = [
        result
        for result in results
        if result.provider_reached and result.expected_extraction is not None
    ]
    scores: list[PositionedExtractionScore] = []
    for result in reached:
        expected_projection = project_extraction(result.expected_extraction)  # type: ignore[arg-type]
        predicted_projection = (
            project_extraction(result.predicted_extraction)
            if result.predicted_extraction is not None
            else CanonicalExtractionProjection(())
        )
        scores.append(score_positioned_extraction(expected_projection, predicted_projection))

    total = FieldCounts(
        tp=sum(score.total.tp for score in scores),
        fp=sum(score.total.fp for score in scores),
        fn=sum(score.total.fn for score in scores),
    )
    aggregate_fields: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for score in scores:
        for metric in score.per_field:
            aggregate_fields[metric.field_name][0] += metric.counts.tp
            aggregate_fields[metric.field_name][1] += metric.counts.fp
            aggregate_fields[metric.field_name][2] += metric.counts.fn
    per_field = tuple(
        _field_metric(name, FieldCounts(tp=counts[0], fp=counts[1], fn=counts[2]))
        for name, counts in sorted(aggregate_fields.items())
    )
    return ExtractionQuality(
        status=ExtractionQualityStatus.AVAILABLE,
        complete_exact_match=_rate(sum(score.exact_match for score in scores), len(scores)),
        field_tp=total.tp,
        field_fp=total.fp,
        field_fn=total.fn,
        precision=_rate(total.tp, total.tp + total.fp),
        recall=_rate(total.tp, total.tp + total.fn),
        f1=_rate(
            2 * total.tp,
            2 * total.tp + total.fp + total.fn,
            undefined=total.tp == 0,
        ),
        per_field=per_field,
        reached_live_gemini_case_count=len(reached),
        reached_live_gemini_case_ids=tuple(result.case_id for result in reached),
        reason="Quality is calculated only for cases that reached the real Gemini provider.",
    )


__all__ = [
    "CanonicalExtractionProjection",
    "CanonicalFieldFact",
    "PositionedExtractionScore",
    "ValidationOutcomeScore",
    "canonicalize_value",
    "project_extraction",
    "score_extraction_quality",
    "score_positioned_extraction",
    "score_validation_outcome",
]
