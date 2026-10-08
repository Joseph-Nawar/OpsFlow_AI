import asyncio
from decimal import Decimal

from opsflow.domain.records import SourceDocumentType
from opsflow.evaluation.corpus import EvaluationBusinessDataProvider
from opsflow.evaluation.models import TrustedCatalog
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.validation.business_data import validate_trusted_business_data
from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedCustomer,
    TrustedProduct,
)


def catalog() -> TrustedCatalog:
    return TrustedCatalog(
        customers=(
            TrustedCustomer(reference="CUST-010", name="Acme Manufacturing", active=True),
            TrustedCustomer(reference="CUST-002", name="Acme Manufacturing", active=True),
            TrustedCustomer(reference="CUST-999", name="Other Buyer", active=True),
        ),
        products=(
            TrustedProduct(
                sku="SKU-001",
                description="Widget",
                active=True,
                currency="USD",
                catalogue_price=Decimal("10.00"),
                available_quantity=Decimal("5"),
            ),
            TrustedProduct(
                sku="SKU-002",
                description="Gadget",
                active=False,
                currency="EUR",
                catalogue_price=Decimal("12.00"),
                available_quantity=Decimal("0"),
            ),
        ),
    )


def request(
    *, customer_reference: str | None = "CUST-010", customer_name: str | None = None
) -> BusinessDataLookupRequest:
    return BusinessDataLookupRequest(
        customer_reference=customer_reference,
        customer_name=customer_name,
        skus=("SKU-001", None, "UNKNOWN-SKU"),
    )


def draft_for(request_value: BusinessDataLookupRequest) -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.EMAIL_BODY,
        customer_name=request_value.customer_name,
        customer_reference=request_value.customer_reference,
        po_number="PO-001",
        order_date=None,
        requested_delivery_date=None,
        currency="USD",
        lines=tuple(
            ExtractedLine(sku=sku, description=None, quantity=None, submitted_price=None)
            for sku in request_value.skus
        ),
        notes=None,
        evidence=(),
    )


def get_data(provider: EvaluationBusinessDataProvider, request_value: BusinessDataLookupRequest):
    return asyncio.run(provider.get_validation_data(request_value))


def test_lookup_is_derived_from_predicted_reference_and_sku_request() -> None:
    provider = EvaluationBusinessDataProvider(catalog())
    data = get_data(provider, request())

    assert [customer.reference for customer in data.customer_candidates] == ["CUST-010"]
    assert data.products_by_line[0] is not None
    assert data.products_by_line[0].sku == "SKU-001"
    assert data.products_by_line[1] is None
    assert data.products_by_line[2] is None
    validate_trusted_business_data(draft_for(request()), data)


def test_wrong_customer_reference_cannot_receive_expected_customer_data() -> None:
    provider = EvaluationBusinessDataProvider(catalog())
    wrong_request = request(customer_reference="CUST-404")

    data = get_data(provider, wrong_request)

    assert data.customer_candidates == ()
    assert all(product is None for product in data.products_by_line[1:])


def test_name_lookup_uses_normalized_exact_match_and_canonical_reference_order() -> None:
    provider = EvaluationBusinessDataProvider(catalog())
    name_request = request(customer_reference=None, customer_name="  ACME   manufacturing ")

    data = get_data(provider, name_request)

    assert [customer.reference for customer in data.customer_candidates] == [
        "CUST-002",
        "CUST-010",
    ]
    validate_trusted_business_data(draft_for(name_request), data)


def test_wrong_name_unknown_sku_and_missing_sku_do_not_get_repaired() -> None:
    provider = EvaluationBusinessDataProvider(catalog())
    wrong_request = BusinessDataLookupRequest(
        customer_reference=None,
        customer_name="Expected Customer That Was Not Predicted",
        skus=("WRONG-SKU", None),
    )

    data = get_data(provider, wrong_request)

    assert data.customer_candidates == ()
    assert data.products_by_line == (None, None)
    assert not hasattr(provider, "expected_extraction")
