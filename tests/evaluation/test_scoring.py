from datetime import date
from decimal import Decimal

import pytest

from opsflow.domain.order import OrderState
from opsflow.domain.records import SourceDocumentType, ValidationSeverity
from opsflow.evaluation.models import (
    ApprovalLevel,
    CaseResult,
    CaseResultStatus,
    EvaluationMode,
    ExpectedExtraction,
    ExpectedLine,
    ExpectedValidation,
    ExtractionQualityStatus,
    RateMetric,
    ValidationRoute,
)
from opsflow.evaluation.scoring import (
    canonicalize_value,
    project_extraction,
    score_extraction_quality,
    score_positioned_extraction,
    score_validation_outcome,
)
from opsflow.extraction.models import ExtractedLine, ExtractionDraft


def expected(
    *, po_number: str = "PO-001", lines: tuple[ExpectedLine, ...] | None = None
) -> ExpectedExtraction:
    return ExpectedExtraction(
        customer_name="Cafe\u0301 Buyer",
        customer_reference="CUST-001",
        po_number=po_number,
        order_date=date(2026, 10, 1),
        requested_delivery_date=date(2026, 10, 8),
        currency="USD",
        notes="Dock A",
        lines=lines
        if lines is not None
        else (
            ExpectedLine(
                sku="SKU-001",
                description="Widget\u0301",
                quantity=Decimal("2.00"),
                submitted_price=Decimal("10.00"),
            ),
        ),
    )


def draft(
    *,
    po_number: str = "PO-001",
    customer_reference: str | None = "CUST-001",
    lines: tuple[ExtractedLine, ...] | None = None,
) -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.EMAIL_BODY,
        customer_name="Café Buyer",
        customer_reference=customer_reference,
        po_number=po_number,
        order_date=date(2026, 10, 1),
        requested_delivery_date=date(2026, 10, 8),
        currency="USD",
        lines=lines
        if lines is not None
        else (
            ExtractedLine(
                sku="SKU-001",
                description="Widget́",
                quantity=Decimal("2"),
                submitted_price=Decimal("10.0"),
            ),
        ),
        notes="Dock A",
        evidence=(),
    )


def case(
    *,
    expected_value: ExpectedExtraction | None = None,
    predicted: ExtractionDraft | None = None,
    reached: bool = False,
    status: CaseResultStatus = CaseResultStatus.SUCCEEDED,
) -> CaseResult:
    return CaseResult(
        case_id="normal-001",
        status=status,
        provider_reached=reached,
        provider_name="gemini" if reached else None,
        provider_call_count=1 if reached else 0,
        failure_code="PROVIDER_FAILED" if status is CaseResultStatus.FAILED else None,
        expected_extraction=expected_value,
        predicted_extraction=predicted,
    )


def test_canonicalization_uses_nfc_exact_strings_decimal_dates_and_nulls() -> None:
    assert canonicalize_value("notes", "Cafe\u0301") == "Café"
    assert canonicalize_value("sku", "SKU-001") != canonicalize_value("sku", "sku-001")
    assert canonicalize_value("po_number", " PO-001 ") == " PO-001 "
    assert canonicalize_value("quantity", Decimal("10.00")) == Decimal("10")
    assert canonicalize_value("order_date", "2026-10-01") == date(2026, 10, 1)
    assert canonicalize_value("notes", None) is None

    with pytest.raises(TypeError, match="binary floating"):
        canonicalize_value("quantity", 10.0)


def test_projected_extractions_compare_as_complete_positioned_business_values() -> None:
    score = score_positioned_extraction(project_extraction(expected()), project_extraction(draft()))

    assert score.exact_match is True
    assert score.total.tp == 11
    assert score.total.fp == 0
    assert score.total.fn == 0
    assert score.micro_precision.value == Decimal("1")
    assert score.micro_recall.value == Decimal("1")
    assert score.micro_f1.value == Decimal("1")


@pytest.mark.parametrize(
    "predicted, expected_tp, expected_fp, expected_fn",
    [
        (draft(po_number="PO-WRONG"), 10, 1, 1),
        (draft(customer_reference=None), 10, 0, 1),
        (
            draft(
                lines=(
                    ExtractedLine(
                        sku="SKU-001",
                        description="Widget́",
                        quantity=Decimal("2"),
                        submitted_price=Decimal("10.0"),
                    ),
                    ExtractedLine(
                        sku="SKU-002",
                        description="Extra",
                        quantity=Decimal("1"),
                        submitted_price=Decimal("3"),
                    ),
                )
            ),
            11,
            4,
            0,
        ),
    ],
)
def test_positioned_field_scoring_counts_wrong_missing_and_extra_values(
    predicted: ExtractionDraft, expected_tp: int, expected_fp: int, expected_fn: int
) -> None:
    score = score_positioned_extraction(
        project_extraction(expected()), project_extraction(predicted)
    )

    assert score.exact_match is False
    assert score.total.tp == expected_tp
    assert score.total.fp == expected_fp
    assert score.total.fn == expected_fn


def test_missing_expected_line_and_reordered_lines_fail_positionally() -> None:
    two_lines = expected(
        lines=(
            ExpectedLine(
                sku="SKU-001",
                description="First",
                quantity=Decimal("1"),
                submitted_price=Decimal("2"),
            ),
            ExpectedLine(
                sku="SKU-002",
                description="Second",
                quantity=Decimal("1"),
                submitted_price=Decimal("3"),
            ),
        )
    )
    reordered = draft(
        lines=(
            ExtractedLine("SKU-002", "Second", Decimal("1"), Decimal("3")),
            ExtractedLine("SKU-001", "First", Decimal("1"), Decimal("2")),
        )
    )
    missing = draft(lines=(ExtractedLine("SKU-001", "First", Decimal("1"), Decimal("2")),))

    reordered_score = score_positioned_extraction(
        project_extraction(two_lines), project_extraction(reordered)
    )
    missing_score = score_positioned_extraction(
        project_extraction(two_lines), project_extraction(missing)
    )

    assert reordered_score.exact_match is False
    assert reordered_score.total.fp == 6
    assert reordered_score.total.fn == 6
    assert missing_score.exact_match is False
    assert missing_score.total.fn == 4


def test_undefined_micro_rates_are_null_not_zero() -> None:
    empty = ExpectedExtraction(
        customer_name=None,
        customer_reference=None,
        po_number=None,
        order_date=None,
        requested_delivery_date=None,
        currency=None,
        notes=None,
        lines=(),
    )
    score = score_positioned_extraction(project_extraction(empty), project_extraction(empty))

    assert score.exact_match is True
    assert score.micro_precision == RateMetric(numerator=0, denominator=0, value=None)
    assert score.micro_recall.value is None
    assert score.micro_f1.value is None


def test_validation_score_compares_route_approval_state_and_code_severity_multiset() -> None:
    expected_validation = ExpectedValidation(
        route=ValidationRoute.NEEDS_REVIEW,
        approval_level=ApprovalLevel.ELEVATED,
        issue_codes=("PRICE_OUTSIDE_TOLERANCE", "INACTIVE_SKU"),
        issue_severities={
            "PRICE_OUTSIDE_TOLERANCE": ValidationSeverity.ERROR,
            "INACTIVE_SKU": ValidationSeverity.WARNING,
        },
        pre_approval_state=OrderState.NEEDS_REVIEW,
        external_execution_eligible=False,
    )
    actual = CaseResult(
        case_id="violation-001",
        status=CaseResultStatus.SUCCEEDED,
        provider_reached=False,
        validation_route=ValidationRoute.NEEDS_REVIEW,
        approval_level=ApprovalLevel.ELEVATED,
        pre_approval_state=OrderState.NEEDS_REVIEW,
        issue_facts=(
            ("INACTIVE_SKU", ValidationSeverity.WARNING),
            ("PRICE_OUTSIDE_TOLERANCE", ValidationSeverity.ERROR),
        ),
    )

    score = score_validation_outcome(expected_validation, actual)

    assert score is not None
    assert score.route_match is True
    assert score.approval_level_match is True
    assert score.pre_approval_state_match is True
    assert score.issue_multiset_match is True
    assert score.overall_match is True


def test_validation_mismatch_exposes_each_component_and_parser_only_bypasses() -> None:
    expected_validation = ExpectedValidation(
        route=ValidationRoute.READY_FOR_APPROVAL,
        approval_level=ApprovalLevel.STANDARD,
        issue_codes=(),
        issue_severities={},
        pre_approval_state=OrderState.READY_FOR_APPROVAL,
        external_execution_eligible=False,
    )
    actual = CaseResult(
        case_id="violation-002",
        status=CaseResultStatus.SUCCEEDED,
        provider_reached=False,
        validation_route=ValidationRoute.NEEDS_REVIEW,
        approval_level=ApprovalLevel.ELEVATED,
        pre_approval_state=OrderState.NEEDS_REVIEW,
        issue_facts=(("UNKNOWN_SKU", ValidationSeverity.ERROR),),
    )
    score = score_validation_outcome(expected_validation, actual)

    assert score is not None
    assert score.route_match is False
    assert score.approval_level_match is False
    assert score.pre_approval_state_match is False
    assert score.issue_multiset_match is False
    assert score.missing_issue_facts == ()
    assert score.unexpected_issue_facts == (("UNKNOWN_SKU", ValidationSeverity.ERROR),)
    assert score.overall_match is False
    assert score_validation_outcome(None, case()) is None


def test_provider_free_quality_is_not_applicable_even_for_perfect_scripted_prediction() -> None:
    result = score_extraction_quality(
        [case(expected_value=expected(), predicted=draft(), reached=False)],
        EvaluationMode.PROVIDER_FREE,
    )

    assert result.status is ExtractionQualityStatus.NOT_APPLICABLE
    assert result.complete_exact_match is None
    assert result.field_tp is None
    assert result.field_fp is None
    assert result.field_fn is None
    assert result.precision is None
    assert result.recall is None
    assert result.f1 is None
    assert "no real model" in result.reason.lower()


def test_live_quality_denominator_contains_only_cases_that_reached_gemini() -> None:
    reached = case(expected_value=expected(), predicted=draft(), reached=True)
    not_reached = case(
        expected_value=expected(), predicted=draft(po_number="PO-WRONG"), reached=False
    )
    failed_after_call = case(
        expected_value=expected(), predicted=None, reached=True, status=CaseResultStatus.FAILED
    )
    fake_reached = CaseResult(
        case_id="scripted-001",
        status=CaseResultStatus.SUCCEEDED,
        provider_reached=True,
        provider_name="fake",
        provider_call_count=1,
        expected_extraction=expected(),
        predicted_extraction=draft(),
    )

    result = score_extraction_quality(
        [reached, not_reached, failed_after_call, fake_reached], EvaluationMode.LIVE_GEMINI
    )

    assert result.status is ExtractionQualityStatus.AVAILABLE
    assert result.reached_live_gemini_case_count == 2
    assert result.complete_exact_match is not None
    assert result.complete_exact_match.numerator == 1
    assert result.complete_exact_match.denominator == 2
    assert result.precision is not None
