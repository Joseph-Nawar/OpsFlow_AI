import asyncio
import inspect
from dataclasses import fields
from decimal import Decimal

import pytest

from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedCustomer,
    TrustedProduct,
)
from opsflow.validation.sandbox import SandboxBusinessDataProvider


def customer(reference: str, name: str, active: bool = True) -> TrustedCustomer:
    return TrustedCustomer(reference, name, active)


def product(
    sku: str,
    *,
    active: bool = True,
    available_quantity: Decimal | None = Decimal("5"),
) -> TrustedProduct:
    return TrustedProduct(sku, "Widget", active, "USD", Decimal("10"), available_quantity)


def provider() -> SandboxBusinessDataProvider:
    return SandboxBusinessDataProvider(
        customers=(
            customer("CUST-002", "Acme Industries"),
            customer("CUST-001", "Acme Industries"),
            customer("CUST-003", "Inactive Industries", active=False),
        ),
        products=(
            product("SKU-002", available_quantity=None),
            product("SKU-001", available_quantity=Decimal("0")),
        ),
    )


def lookup(provider_value: SandboxBusinessDataProvider, request: BusinessDataLookupRequest):
    return asyncio.run(provider_value.get_validation_data(request))


def test_reference_is_authoritative_over_customer_name() -> None:
    result = lookup(
        provider(),
        BusinessDataLookupRequest("CUST-001", "Inactive Industries", (None,)),
    )

    assert result.customer_candidates == (customer("CUST-001", "Acme Industries"),)


def test_customer_name_lookup_returns_normalized_exact_ambiguous_candidates_in_order() -> None:
    result = lookup(
        provider(),
        BusinessDataLookupRequest(None, "  ACME\u00a0 INDUSTRIES ", (None,)),
    )

    assert tuple(item.reference for item in result.customer_candidates) == ("CUST-001", "CUST-002")


def test_customer_name_matching_does_not_fuzz_or_transliterate() -> None:
    result = lookup(
        provider(),
        BusinessDataLookupRequest(None, "Acme Industrie", (None,)),
    )

    assert result.customer_candidates == ()


def test_exact_case_sensitive_sku_matching_has_no_description_fallback() -> None:
    result = lookup(
        provider(),
        BusinessDataLookupRequest(None, None, ("SKU-001", "sku-001", None, "Widget")),
    )

    assert result.products_by_line[0] == product("SKU-001", available_quantity=Decimal("0"))
    assert result.products_by_line[1:] == (None, None, None)


def test_unknown_inactive_and_inventory_states_remain_distinct() -> None:
    result = lookup(
        provider(),
        BusinessDataLookupRequest(None, "Inactive Industries", ("SKU-001", "SKU-002", "MISSING")),
    )

    assert result.customer_candidates == (customer("CUST-003", "Inactive Industries", False),)
    assert result.products_by_line[0].available_quantity == Decimal("0")
    assert result.products_by_line[1].available_quantity is None
    assert result.products_by_line[2] is None


def test_repeated_equal_requests_return_equal_deterministic_snapshots() -> None:
    request = BusinessDataLookupRequest(None, "acme industries", ("SKU-002", "SKU-001"))

    assert lookup(provider(), request) == lookup(provider(), request)


def test_sandbox_rejects_duplicate_exact_customer_references_and_skus() -> None:
    with pytest.raises(ValueError):
        SandboxBusinessDataProvider(
            customers=(customer("CUST-001", "One"), customer("CUST-001", "Two")),
            products=(),
        )
    with pytest.raises(ValueError):
        SandboxBusinessDataProvider(
            customers=(),
            products=(product("SKU-001"), product("SKU-001")),
        )


def test_sandbox_configuration_contains_only_customers_and_products() -> None:
    names = {item.name for item in fields(SandboxBusinessDataProvider)}

    assert names == {"customers", "products"}
    assert set(inspect.signature(SandboxBusinessDataProvider).parameters) == {
        "customers",
        "products",
    }
