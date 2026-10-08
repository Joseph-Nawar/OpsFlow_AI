from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from opsflow.domain.order import OrderState
from opsflow.domain.records import SourceDocumentType
from opsflow.evaluation.models import (
    ApprovalLevel,
    ApprovalScenario,
    CaseCategory,
    CorpusCase,
    CorpusManifest,
    ExpectedExtraction,
    ExpectedLine,
    ExpectedValidation,
    ReplayDisposition,
    ReplayScenario,
    SourceSpec,
    TrustedBusinessDataExpectation,
)
from opsflow.order_sync.contracts import OrderSyncFailureCode
from opsflow.validation.models import ValidationFacts, ValidationRoute


def valid_source() -> SourceSpec:
    return SourceSpec(
        path="documents/normal.txt",
        document_type=SourceDocumentType.EMAIL_BODY,
        mime_type="text/plain",
        sha256="a" * 64,
    )


def valid_extraction() -> ExpectedExtraction:
    return ExpectedExtraction(
        customer_name="Acme Manufacturing",
        customer_reference="CUST-001",
        po_number="PO-001",
        order_date=date(2026, 10, 1),
        requested_delivery_date=date(2026, 10, 8),
        currency="USD",
        notes=None,
        lines=(
            ExpectedLine(
                sku="SKU-001",
                description="Widget",
                quantity=Decimal("2"),
                submitted_price=Decimal("10.00"),
            ),
        ),
    )


def valid_case(**overrides: object) -> CorpusCase:
    values: dict[str, object] = {
        "case_id": "normal-001",
        "primary_category": CaseCategory.NORMAL,
        "tags": ("clean",),
        "source": valid_source(),
        "expected_extraction": valid_extraction(),
    }
    values.update(overrides)
    return CorpusCase.model_validate(values)


def valid_manifest_payload() -> dict[str, object]:
    return {
        "schema_version": "opsflow-evaluation-corpus/v1",
        "corpus_version": "1.0.0",
        "cases": [
            {
                "case_id": "normal-001",
                "primary_category": "normal",
                "tags": ["clean"],
                "source": {
                    "path": "documents/normal.txt",
                    "document_type": "EMAIL_BODY",
                    "mime_type": "text/plain",
                    "sha256": "a" * 64,
                },
                "expected_extraction": {
                    "customer_name": "Acme Manufacturing",
                    "customer_reference": "CUST-001",
                    "po_number": "PO-001",
                    "order_date": "2026-10-01",
                    "requested_delivery_date": "2026-10-08",
                    "currency": "USD",
                    "notes": None,
                    "lines": [
                        {
                            "sku": "SKU-001",
                            "description": "Widget",
                            "quantity": "2",
                            "submitted_price": "10.00",
                        }
                    ],
                },
            }
        ],
    }


def valid_validation() -> ExpectedValidation:
    return ExpectedValidation(
        route=ValidationRoute.READY_FOR_APPROVAL,
        approval_level=ApprovalLevel.STANDARD,
        issue_codes=(),
        issue_severities={},
        pre_approval_state=OrderState.READY_FOR_APPROVAL,
        external_execution_eligible=False,
    )


def test_manifest_contract_accepts_named_human_readable_ground_truth() -> None:
    manifest = CorpusManifest.model_validate(valid_manifest_payload())

    assert manifest.corpus_version == "1.0.0"
    assert manifest.cases[0].expected_extraction is not None
    assert manifest.cases[0].expected_extraction.lines[0].submitted_price == Decimal("10.00")


def test_manifest_rejects_malformed_manifest() -> None:
    payload = valid_manifest_payload()
    payload.pop("cases")

    with pytest.raises(ValidationError):
        CorpusManifest.model_validate(payload)


def test_manifest_rejects_unsupported_category_and_corpus_format() -> None:
    category_payload = valid_manifest_payload()
    category_payload["cases"][0]["primary_category"] = "invented"  # type: ignore[index]
    with pytest.raises(ValidationError):
        CorpusManifest.model_validate(category_payload)

    with pytest.raises(ValidationError):
        SourceSpec(
            path="documents/form.bin",
            document_type=SourceDocumentType.FORM,
            mime_type="application/octet-stream",
            sha256="a" * 64,
        )


def test_manifest_rejects_duplicate_case_ids() -> None:
    payload = valid_manifest_payload()
    payload["cases"].append(payload["cases"][0])  # type: ignore[index]

    with pytest.raises(ValidationError, match="case_id"):
        CorpusManifest.model_validate(payload)


def test_parser_only_case_may_omit_extraction_but_normal_case_may_not() -> None:
    with pytest.raises(ValidationError, match="expected_extraction"):
        valid_case(expected_extraction=None)

    parser_only = valid_case(
        case_id="parser-only-001",
        primary_category=CaseCategory.SECURITY,
        tags=("parser_only", "malformed"),
        expected_extraction=None,
    )
    assert parser_only.expected_extraction is None


def test_validation_expectations_are_conditional_and_paired_with_trusted_facts() -> None:
    with pytest.raises(ValidationError, match="expected_validation"):
        valid_case(tags=("validation",), expected_validation=None)

    with pytest.raises(ValidationError, match="trusted_business_data"):
        valid_case(tags=("validation",), expected_validation=valid_validation())

    case = valid_case(
        tags=("validation",),
        expected_validation=valid_validation(),
        trusted_business_data=TrustedBusinessDataExpectation(
            fixture_path="trusted-data/catalog.json",
            facts=ValidationFacts(
                duplicate_customer_po=False,
                document_already_processed=False,
            ),
        ),
    )
    assert case.expected_validation is not None


def test_optional_scenarios_are_restricted_to_their_categories() -> None:
    replay = ReplayScenario(
        duplicate_group_id="dup-001",
        seed_case_id="normal-001",
        replay_attempt_count=1,
        expected_disposition=ReplayDisposition.STAND_DOWN,
    )
    with pytest.raises(ValidationError, match="replay"):
        valid_case(replay=replay)

    with pytest.raises(ValidationError, match="replay"):
        valid_case(
            primary_category=CaseCategory.DUPLICATE,
            tags=("duplicate",),
            replay=None,
        )

    with pytest.raises(ValidationError, match="approval"):
        valid_case(
            approval=ApprovalScenario(
                role="order_approver",
                action="approve",
                expected_state=OrderState.APPROVED,
            )
        )

    assert OrderSyncFailureCode.PROVIDER_UNAVAILABLE.value == "PROVIDER_UNAVAILABLE"
