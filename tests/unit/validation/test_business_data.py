from datetime import date
from decimal import Decimal

import pytest

from opsflow.domain import SourceDocumentType
from opsflow.extraction import ExtractedLine, ExtractionDraft
from opsflow.validation.business_data import (
    TrustedBusinessDataContractError,
    normalize_customer_name,
    validate_trusted_business_data,
)
from opsflow.validation.models import TrustedBusinessData, TrustedCustomer, TrustedProduct


def draft(line_count: int = 1) -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme Industries",
        customer_reference=None,
        po_number="PO-1001",
        order_date=date(2026, 9, 1),
        requested_delivery_date=date(2026, 9, 15),
        currency="USD",
        lines=tuple(
            ExtractedLine("SKU-001", "Widget", Decimal("1"), Decimal("10"))
            for _ in range(line_count)
        ),
        notes=None,
        evidence=(),
    )


def customer(reference: str, name: str = "Acme Industries", active: bool = True) -> TrustedCustomer:
    return TrustedCustomer(reference, name, active)


def product(
    sku: str,
    *,
    active: bool = True,
    available_quantity: Decimal | None = Decimal("5"),
) -> TrustedProduct:
    return TrustedProduct(sku, "Widget", active, "USD", Decimal("10"), available_quantity)


def test_normalize_customer_name_uses_casefold_unicode_whitespace_and_ascii_join() -> None:
    assert normalize_customer_name("  STRAẞE\u00a0\tIndustries\n ") == "strasse industries"


def test_validator_accepts_provider_data_matching_draft_line_count() -> None:
    data = TrustedBusinessData((customer("CUST-001"),), (product("SKU-001"),))

    validate_trusted_business_data(draft(), data)


def test_validator_rejects_products_by_line_length_mismatch() -> None:
    data = TrustedBusinessData((customer("CUST-001"),), ())

    with pytest.raises(TrustedBusinessDataContractError):
        validate_trusted_business_data(draft(), data)


def test_validator_rejects_duplicate_customer_references() -> None:
    data = TrustedBusinessData(
        (customer("CUST-001"), customer("CUST-001", "Other Industries")),
        (product("SKU-001"),),
    )

    with pytest.raises(TrustedBusinessDataContractError):
        validate_trusted_business_data(draft(), data)


def test_validator_rejects_noncanonical_customer_candidate_order() -> None:
    data = TrustedBusinessData(
        (customer("CUST-002"), customer("CUST-001")),
        (product("SKU-001"),),
    )

    with pytest.raises(TrustedBusinessDataContractError):
        validate_trusted_business_data(draft(), data)


def test_validator_rejects_non_trusted_business_data_values() -> None:
    with pytest.raises(TrustedBusinessDataContractError):
        validate_trusted_business_data(draft(), object())  # type: ignore[arg-type]
