import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from opsflow.domain.order import OrderState
from opsflow.domain.records import SourceDocumentType
from opsflow.evaluation.corpus import (
    load_catalog,
    load_manifest,
    resolve_manifest_source,
    verify_source_sha256,
)
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

    with pytest.raises(ValidationError, match="MIME"):
        SourceSpec(
            path="documents/not-a-csv.csv",
            document_type=SourceDocumentType.CSV,
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


def test_source_digest_and_path_guards_reject_malformed_or_escaping_inputs(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("synthetic source", encoding="utf-8")

    with pytest.raises(ValueError, match="lowercase"):
        verify_source_sha256(source, "A" * 64)
    with pytest.raises(ValueError, match="does not match"):
        verify_source_sha256(source, "a" * 64)
    with pytest.raises(ValueError, match="relative"):
        resolve_manifest_source(tmp_path, "../source.txt")
    with pytest.raises(ValueError, match="relative"):
        resolve_manifest_source(tmp_path, "/tmp/source.txt")


def test_symlink_escape_is_rejected_before_source_read(tmp_path: Path) -> None:
    outside = tmp_path.parent / "evaluation-outside-source.txt"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "documents"
    link.symlink_to(outside.parent, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes"):
        resolve_manifest_source(tmp_path, "documents/evaluation-outside-source.txt")


def test_repeated_source_sha_is_allowed_for_intentional_replay_cases(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    source = documents / "replay.txt"
    source.write_text("same replay identity", encoding="utf-8")
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()

    first = valid_manifest_payload()["cases"][0].copy()  # type: ignore[index]
    first.update(
        {
            "case_id": "duplicate-001",
            "primary_category": "duplicate",
            "tags": ["duplicate"],
            "source": {
                "path": "documents/replay.txt",
                "document_type": "EMAIL_BODY",
                "mime_type": "text/plain",
                "sha256": digest,
            },
            "replay": {
                "duplicate_group_id": "replay-group-001",
                "seed_case_id": "duplicate-001",
                "replay_attempt_count": 1,
                "expected_disposition": "STANDING_DOWN",
            },
        }
    )
    second = json.loads(json.dumps(first))
    second["case_id"] = "duplicate-002"
    second["replay"]["seed_case_id"] = "duplicate-001"

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "opsflow-evaluation-corpus/v1",
                "corpus_version": "1.0.0",
                "cases": [first, second],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_manifest(tmp_path)
    assert len(manifest.cases) == 2
    assert manifest.cases[0].source.sha256 == manifest.cases[1].source.sha256


def test_v1_corpus_has_exact_approved_distribution() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))

    assert manifest.corpus_version == "1.0.0"
    assert len(manifest.cases) == 36
    assert {case.primary_category for case in manifest.cases} == set(CaseCategory)
    assert {
        category: sum(case.primary_category is category for case in manifest.cases)
        for category in CaseCategory
    } == {
        CaseCategory.NORMAL: 10,
        CaseCategory.EDGE: 8,
        CaseCategory.SECURITY: 4,
        CaseCategory.DETERMINISTIC_VIOLATION: 7,
        CaseCategory.DUPLICATE: 4,
        CaseCategory.RETRY_RECOVERY: 3,
    }
    assert {
        document_type: sum(case.source.document_type is document_type for case in manifest.cases)
        for document_type in (
            SourceDocumentType.EMAIL_BODY,
            SourceDocumentType.CSV,
            SourceDocumentType.XLSX,
            SourceDocumentType.PDF,
        )
    } == {
        SourceDocumentType.EMAIL_BODY: 9,
        SourceDocumentType.CSV: 9,
        SourceDocumentType.XLSX: 9,
        SourceDocumentType.PDF: 9,
    }


def test_v1_manifest_references_a_synthetic_lookup_catalog() -> None:
    manifest = load_manifest(Path("evals/corpus/v1"))
    catalog = load_catalog(Path("evals/corpus/v1") / manifest.trusted_catalog_path)

    assert catalog.customers
    assert catalog.products
    assert all(customer.reference.startswith("CUST-") for customer in catalog.customers)
    assert all(product.sku.startswith("SKU-") for product in catalog.products)
