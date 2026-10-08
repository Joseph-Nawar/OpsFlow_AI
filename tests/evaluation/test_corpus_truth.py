import asyncio
from collections import Counter
from pathlib import Path

from opsflow.domain.order import OrderState
from opsflow.evaluation.corpus import EvaluationBusinessDataProvider, load_catalog, load_manifest
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.validation.engine import validate
from opsflow.validation.models import BusinessDataLookupRequest, ValidationContext
from opsflow.validation.policy import ValidationPolicy


def _draft_from_expected(case) -> ExtractionDraft:
    expected = case.expected_extraction
    assert expected is not None
    return ExtractionDraft(
        source_sha256=case.source.sha256,
        source_document_type=case.source.document_type,
        customer_name=expected.customer_name,
        customer_reference=expected.customer_reference,
        po_number=expected.po_number,
        order_date=expected.order_date,
        requested_delivery_date=expected.requested_delivery_date,
        currency=expected.currency,
        lines=tuple(
            ExtractedLine(
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                submitted_price=line.submitted_price,
            )
            for line in expected.lines
        ),
        notes=expected.notes,
        evidence=(),
    )


def test_every_routed_case_matches_the_real_validation_engine() -> None:
    corpus_root = Path("evals/corpus/v1")
    manifest = load_manifest(corpus_root)
    catalog = load_catalog(corpus_root / manifest.trusted_catalog_path)
    provider = EvaluationBusinessDataProvider(catalog)
    context = ValidationContext(evaluation_date=manifest.benchmark_context.evaluation_date)
    policy = ValidationPolicy(
        supported_currencies=manifest.benchmark_context.supported_currencies,
        price_tolerance_fraction=manifest.benchmark_context.price_tolerance_fraction,
        high_value_threshold=manifest.benchmark_context.high_value_threshold,
    )

    for case in manifest.cases:
        if case.expected_validation is None:
            continue
        assert case.trusted_business_data is not None
        draft = _draft_from_expected(case)
        request = BusinessDataLookupRequest(
            customer_reference=draft.customer_reference,
            customer_name=draft.customer_name,
            skus=tuple(line.sku for line in draft.lines),
        )
        trusted = asyncio.run(provider.get_validation_data(request))
        actual = validate(draft, trusted, case.trusted_business_data.facts, policy, context)
        expected = case.expected_validation

        assert actual.route is expected.route, case.case_id
        assert actual.approval_level is expected.approval_level, case.case_id
        assert OrderState(actual.route.value) is expected.pre_approval_state, case.case_id
        assert Counter((issue.rule_code, issue.severity) for issue in actual.issues) == Counter(
            (code, expected.issue_severities[code]) for code in expected.issue_codes
        ), case.case_id
