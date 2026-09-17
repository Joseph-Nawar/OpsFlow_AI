from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

import pytest

from opsflow.domain import ValidationIssue, ValidationSeverity
from opsflow.validation.models import (
    ApprovalLevel,
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
    ValidatedOrderData,
    ValidatedOrderLine,
    ValidationContext,
    ValidationFacts,
    ValidationResult,
    ValidationRoute,
)

DATE = date(2026, 9, 17)


def customer(**overrides: object) -> TrustedCustomer:
    values: dict[str, object] = {
        "reference": "CUST-001",
        "name": "Acme Industries",
        "active": True,
    }
    values.update(overrides)
    return TrustedCustomer(**values)


def product(**overrides: object) -> TrustedProduct:
    values: dict[str, object] = {
        "sku": "SKU-001",
        "description": "Widget",
        "active": True,
        "currency": "USD",
        "catalogue_price": Decimal("10.00"),
        "available_quantity": Decimal("5"),
    }
    values.update(overrides)
    return TrustedProduct(**values)


def line(**overrides: object) -> ValidatedOrderLine:
    values: dict[str, object] = {
        "sku": "SKU-001",
        "description": "Widget",
        "quantity": Decimal("2"),
        "submitted_price": Decimal("10"),
        "trusted_catalogue_price": Decimal("10"),
    }
    values.update(overrides)
    return ValidatedOrderLine(**values)


def order_data(**overrides: object) -> ValidatedOrderData:
    values: dict[str, object] = {
        "customer_reference": "CUST-001",
        "po_number": "PO-1001",
        "order_date": date(2026, 9, 1),
        "requested_delivery_date": date(2026, 9, 15),
        "currency": "USD",
        "lines": (line(),),
    }
    values.update(overrides)
    return ValidatedOrderData(**values)


def test_routes_and_approval_levels_have_exact_enum_values() -> None:
    assert issubclass(ValidationRoute, Enum)
    assert [(member.name, member.value) for member in ValidationRoute] == [
        ("NEEDS_REVIEW", "NEEDS_REVIEW"),
        ("READY_FOR_APPROVAL", "READY_FOR_APPROVAL"),
    ]
    assert [(member.name, member.value) for member in ApprovalLevel] == [
        ("STANDARD", "STANDARD"),
        ("ELEVATED", "ELEVATED"),
    ]


def test_contract_records_are_frozen_and_slotted() -> None:
    records = (
        ValidationContext(DATE),
        ValidationFacts(False, False),
        customer(),
        product(),
        TrustedBusinessData((customer(),), (product(),)),
        BusinessDataLookupRequest("CUST-001", None, ("SKU-001",)),
        line(),
        order_data(),
        ValidationResult(
            issues=(),
            route=ValidationRoute.READY_FOR_APPROVAL,
            approval_level=ApprovalLevel.STANDARD,
            order_total=Decimal("20"),
            validated_order_data=order_data(),
        ),
    )

    for record in records:
        assert is_dataclass(record)
        assert record.__slots__
        with pytest.raises(FrozenInstanceError):
            setattr(record, fields(record)[0].name, None)


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (lambda: TrustedBusinessData((customer(),), (product(),)), "customer_candidates"),
        (lambda: TrustedBusinessData((customer(),), (product(),)), "products_by_line"),
        (lambda: BusinessDataLookupRequest("CUST-001", None, ("SKU-001",)), "skus"),
        (order_data, "lines"),
    ],
)
def test_collection_contracts_reject_mutable_replacements(factory: object, field: str) -> None:
    value = factory()  # type: ignore[operator]
    replacement: object
    if field in {"customer_candidates", "products_by_line", "skus", "lines"}:
        replacement = []
    else:
        replacement = getattr(value, field)

    values = {item.name: getattr(value, item.name) for item in fields(value)}
    values[field] = replacement
    with pytest.raises(ValueError):
        type(value)(**values)


@pytest.mark.parametrize("bad_value", [1, 0, "true", None])
def test_validation_facts_require_strict_booleans(bad_value: object) -> None:
    with pytest.raises(ValueError):
        ValidationFacts(bad_value, False)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ValidationFacts(False, bad_value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    ["catalogue_price", "available_quantity"],
)
@pytest.mark.parametrize("bad_value", [Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")])
def test_trusted_product_rejects_negative_or_non_finite_decimals(
    field: str, bad_value: Decimal
) -> None:
    with pytest.raises(ValueError):
        product(**{field: bad_value})


def test_trusted_product_allows_unknown_inventory_but_requires_decimal_values() -> None:
    assert product(available_quantity=None).available_quantity is None
    with pytest.raises(ValueError):
        product(catalogue_price=10)
    with pytest.raises(ValueError):
        product(available_quantity=1)


@pytest.mark.parametrize("field", ["sku", "customer_reference", "po_number"])
def test_promotable_data_requires_nonblank_identity(field: str) -> None:
    with pytest.raises(ValueError):
        if field == "sku":
            line(sku=" ")
        else:
            order_data(**{field: "\t"})


def test_promotable_data_requires_positive_quantity_and_nonnegative_prices() -> None:
    with pytest.raises(ValueError):
        line(quantity=Decimal("0"))
    with pytest.raises(ValueError):
        line(quantity=Decimal("NaN"))
    with pytest.raises(ValueError):
        line(submitted_price=Decimal("-0.01"))
    with pytest.raises(ValueError):
        line(trusted_catalogue_price=Decimal("-0.01"))


def test_validation_result_rejects_error_with_promotable_data() -> None:
    issue = ValidationIssue(
        rule_code="CUSTOMER_REQUIRED",
        severity=ValidationSeverity.ERROR,
        field="customer",
        expected="customer_reference or customer_name",
        actual=None,
        explanation="Customer reference or customer name is required.",
    )
    with pytest.raises(ValueError):
        ValidationResult(
            issues=(issue,),
            route=ValidationRoute.NEEDS_REVIEW,
            approval_level=ApprovalLevel.STANDARD,
            order_total=None,
            validated_order_data=order_data(),
        )


def test_validation_result_requires_typed_issue_route_and_approval() -> None:
    with pytest.raises(ValueError):
        ValidationResult((), "READY_FOR_APPROVAL", ApprovalLevel.STANDARD, None, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ValidationResult((), ValidationRoute.READY_FOR_APPROVAL, "STANDARD", None, None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ValidationResult(
            ("not an issue",),
            ValidationRoute.READY_FOR_APPROVAL,
            ApprovalLevel.STANDARD,
            None,
            None,
        )  # type: ignore[arg-type]
