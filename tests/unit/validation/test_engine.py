from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from opsflow.domain import Order, OrderLine, OrderState, SourceDocumentType, ValidationSeverity
from opsflow.extraction import ExtractedLine, ExtractionDraft
from opsflow.review.composition import build_demo_review_runtime
from opsflow.validation.engine import approved_order_trusted_data_issues, validate
from opsflow.validation.models import (
    ApprovalLevel,
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
from opsflow.validation.policy import ValidationPolicy

EVALUATION_DATE = date(2026, 9, 17)


def extracted_line(**overrides: object) -> ExtractedLine:
    values: dict[str, object] = {
        "sku": "SKU-001",
        "description": "Extracted widget",
        "quantity": Decimal("2"),
        "submitted_price": Decimal("10"),
    }
    values.update(overrides)
    return ExtractedLine(**values)


def draft(**overrides: object) -> ExtractionDraft:
    values: dict[str, object] = {
        "source_sha256": "a" * 64,
        "source_document_type": SourceDocumentType.PDF,
        "customer_name": None,
        "customer_reference": "CUST-001",
        "po_number": "PO-1001",
        "order_date": date(2026, 9, 1),
        "requested_delivery_date": date(2026, 9, 20),
        "currency": "USD",
        "lines": (extracted_line(),),
        "notes": None,
        "evidence": (),
    }
    values.update(overrides)
    return ExtractionDraft(**values)


def customer(
    reference: str = "CUST-001", name: str = "Acme Industries", active: bool = True
) -> TrustedCustomer:
    return TrustedCustomer(reference, name, active)


def product(
    sku: str = "SKU-001",
    *,
    description: str | None = "Trusted widget",
    active: bool = True,
    currency: str = "USD",
    catalogue_price: Decimal | None = Decimal("10"),
    available_quantity: Decimal | None = Decimal("100"),
) -> TrustedProduct:
    return TrustedProduct(
        sku,
        description,
        active,
        currency,
        catalogue_price,
        available_quantity,
    )


def business_data(
    *,
    customers: tuple[TrustedCustomer, ...] = (customer(),),
    products: tuple[TrustedProduct | None, ...] | None = None,
) -> TrustedBusinessData:
    products_by_line = (product(),) if products is None else products
    return TrustedBusinessData(
        customers,
        products_by_line,
    )


def facts(duplicate_customer_po: bool = False, document_already_processed: bool = False):
    return ValidationFacts(duplicate_customer_po, document_already_processed)


def policy(
    *,
    tolerance: Decimal = Decimal("0.10"),
    threshold: Decimal = Decimal("100"),
    currencies: tuple[str, ...] = ("USD", "EUR"),
) -> ValidationPolicy:
    return ValidationPolicy(currencies, tolerance, threshold)


def context() -> ValidationContext:
    return ValidationContext(EVALUATION_DATE)


def result(
    draft_value: ExtractionDraft | None = None,
    data: TrustedBusinessData | None = None,
    validation_facts: ValidationFacts | None = None,
    validation_policy: ValidationPolicy | None = None,
) -> ValidationResult:
    draft_value = draft() if draft_value is None else draft_value
    data = business_data() if data is None else data
    validation_facts = facts() if validation_facts is None else validation_facts
    validation_policy = policy() if validation_policy is None else validation_policy
    return validate(draft_value, data, validation_facts, validation_policy, context())


def issue(result_value: ValidationResult, rule_code: str):
    return next(item for item in result_value.issues if item.rule_code == rule_code)


def codes(result_value: ValidationResult) -> list[str]:
    return [item.rule_code for item in result_value.issues]


def test_valid_order_returns_complete_trusted_data_and_exact_decimal_total() -> None:
    value = result()

    assert value.issues == ()
    assert value.route is ValidationRoute.READY_FOR_APPROVAL
    assert value.approval_level is ApprovalLevel.STANDARD
    assert value.order_total == Decimal("20")
    assert value.validated_order_data == ValidatedOrderData(
        customer_reference="CUST-001",
        po_number="PO-1001",
        order_date=date(2026, 9, 1),
        requested_delivery_date=date(2026, 9, 20),
        currency="USD",
        lines=(
            ValidatedOrderLine(
                sku="SKU-001",
                description="Trusted widget",
                quantity=Decimal("2"),
                submitted_price=Decimal("10"),
                trusted_catalogue_price=Decimal("10"),
            ),
        ),
    )


def test_customer_required_is_blocking_and_has_exact_issue_shape() -> None:
    value = result(
        draft_value=draft(customer_reference=None, customer_name=None),
        data=business_data(customers=()),
    )

    assert value.route is ValidationRoute.NEEDS_REVIEW
    assert value.validated_order_data is None
    assert value.issues == (
        type(issue(value, "CUSTOMER_REQUIRED"))(
            rule_code="CUSTOMER_REQUIRED",
            severity=ValidationSeverity.ERROR,
            field="customer",
            expected="customer_reference or customer_name",
            actual=None,
            explanation="Customer reference or customer name is required.",
        ),
    )


def test_unknown_ambiguous_and_inactive_customer_rules_are_exact() -> None:
    unknown = result(data=business_data(customers=()))
    assert unknown.issues == (
        type(issue(unknown, "UNKNOWN_CUSTOMER"))(
            "UNKNOWN_CUSTOMER",
            ValidationSeverity.ERROR,
            "customer_reference",
            "one exact trusted customer",
            "CUST-001",
            "No exact trusted customer matched the supplied identity.",
        ),
    )

    ambiguous = result(
        draft_value=draft(customer_reference=None, customer_name="Acme Industries"),
        data=business_data(
            customers=(customer("CUST-001"), customer("CUST-002")),
        ),
    )
    assert ambiguous.issues == (
        type(issue(ambiguous, "AMBIGUOUS_CUSTOMER"))(
            "AMBIGUOUS_CUSTOMER",
            ValidationSeverity.ERROR,
            "customer_name",
            "one exact trusted customer",
            {"identity": "Acme Industries", "candidate_count": 2},
            "Multiple exact trusted customers matched the supplied identity.",
        ),
    )

    inactive = result(data=business_data(customers=(customer(active=False),)))
    assert inactive.issues == (
        type(issue(inactive, "INACTIVE_CUSTOMER"))(
            "INACTIVE_CUSTOMER",
            ValidationSeverity.ERROR,
            "customer_reference",
            "active trusted customer",
            "CUST-001",
            "The matched customer is inactive.",
        ),
    )


def test_po_required_precedes_duplicate_and_duplicate_uses_canonical_identity() -> None:
    missing = result(
        draft_value=draft(po_number=None),
        validation_facts=facts(duplicate_customer_po=True),
    )
    assert codes(missing) == ["PO_NUMBER_REQUIRED"]

    duplicate = result(validation_facts=facts(duplicate_customer_po=True))
    assert duplicate.issues == (
        type(issue(duplicate, "DUPLICATE_CUSTOMER_PO"))(
            "DUPLICATE_CUSTOMER_PO",
            ValidationSeverity.ERROR,
            "po_number",
            "no existing exact customer+PO pair",
            {"customer_reference": "CUST-001", "po_number": "PO-1001"},
            "The customer-scoped purchase-order reference already exists.",
        ),
    )


def test_duplicate_po_is_suppressed_for_unknown_or_ambiguous_customer() -> None:
    unknown = result(data=business_data(customers=()), validation_facts=facts(True))
    assert codes(unknown) == ["UNKNOWN_CUSTOMER"]

    ambiguous = result(
        draft_value=draft(customer_reference=None, customer_name="Acme Industries"),
        data=business_data(customers=(customer("CUST-001"), customer("CUST-002"))),
        validation_facts=facts(True),
    )
    assert codes(ambiguous) == ["AMBIGUOUS_CUSTOMER"]


def test_source_duplicate_consumes_only_validation_facts() -> None:
    value = result(validation_facts=facts(document_already_processed=True))

    assert value.issues == (
        type(issue(value, "DOCUMENT_ALREADY_PROCESSED"))(
            "DOCUMENT_ALREADY_PROCESSED",
            ValidationSeverity.ERROR,
            "source_sha256",
            "no earlier processed snapshot for this SHA-256",
            "a" * 64,
            "The source document SHA-256 was already processed under another order or source.",
        ),
    )


def test_date_required_rules_do_not_emit_comparison_cascades() -> None:
    value = result(draft_value=draft(order_date=None, requested_delivery_date=None))

    assert codes(value) == ["ORDER_DATE_REQUIRED", "DELIVERY_DATE_REQUIRED"]


def test_date_comparisons_use_explicit_evaluation_date() -> None:
    future = result(draft_value=draft(order_date=date(2026, 9, 18)))
    assert issue(future, "ORDER_DATE_IN_FUTURE").expected == "order_date <= evaluation_date"
    assert issue(future, "ORDER_DATE_IN_FUTURE").actual == {
        "order_date": "2026-09-18",
        "evaluation_date": "2026-09-17",
    }

    past_delivery = result(draft_value=draft(requested_delivery_date=date(2026, 9, 16)))
    assert issue(past_delivery, "DELIVERY_DATE_IN_PAST").actual == {
        "requested_delivery_date": "2026-09-16",
        "evaluation_date": "2026-09-17",
    }

    out_of_order = result(
        draft_value=draft(
            order_date=date(2026, 9, 10),
            requested_delivery_date=date(2026, 9, 9),
        )
    )
    assert codes(out_of_order) == ["DELIVERY_DATE_IN_PAST", "DELIVERY_BEFORE_ORDER_DATE"]


def test_currency_required_and_unsupported_rules_are_distinct() -> None:
    missing = result(draft_value=draft(currency=None))
    assert codes(missing) == ["CURRENCY_REQUIRED"]
    assert issue(missing, "CURRENCY_REQUIRED").expected == "non-null currency"

    unsupported = result(draft_value=draft(currency="GBP"))
    assert codes(unsupported) == ["UNSUPPORTED_CURRENCY"]
    assert issue(unsupported, "UNSUPPORTED_CURRENCY").expected == ["USD", "EUR"]
    assert issue(unsupported, "UNSUPPORTED_CURRENCY").actual == "GBP"


def test_empty_lines_emit_only_order_lines_required() -> None:
    value = result(draft_value=draft(lines=()), data=business_data(products=()))

    assert value.issues == (
        type(issue(value, "ORDER_LINES_REQUIRED"))(
            "ORDER_LINES_REQUIRED",
            ValidationSeverity.ERROR,
            "lines",
            "at least one line",
            [],
            "At least one order line is required.",
        ),
    )
    assert value.order_total is None


def test_line_required_rules_do_not_run_product_dependent_checks() -> None:
    value = result(
        draft_value=draft(lines=(extracted_line(sku=None, quantity=None, submitted_price=None),)),
        data=business_data(products=(None,)),
    )

    assert codes(value) == ["SKU_REQUIRED", "QUANTITY_REQUIRED", "SUBMITTED_PRICE_REQUIRED"]
    assert [item.field for item in value.issues] == [
        "lines[0].sku",
        "lines[0].quantity",
        "lines[0].submitted_price",
    ]


def test_invalid_line_prerequisites_suppress_total_and_high_value_classification() -> None:
    value = result(
        draft_value=draft(lines=(extracted_line(quantity=None),)),
        data=business_data(products=(product(),)),
        validation_policy=policy(threshold=Decimal("0")),
    )

    assert value.order_total is None
    assert "HIGH_VALUE_APPROVAL_REQUIRED" not in codes(value)
    assert value.route is ValidationRoute.NEEDS_REVIEW
    assert value.validated_order_data is None


def test_unknown_and_inactive_sku_rules_have_no_description_fallback() -> None:
    unknown = result(
        draft_value=draft(lines=(extracted_line(sku="sku-001"),)),
        data=business_data(products=(None,)),
    )
    assert codes(unknown) == ["UNKNOWN_SKU"]
    assert issue(unknown, "UNKNOWN_SKU").field == "lines[0].sku"

    inactive = result(data=business_data(products=(product(active=False),)))
    assert codes(inactive) == ["INACTIVE_SKU"]
    assert issue(inactive, "INACTIVE_SKU").actual == "SKU-001"


def test_quantity_and_inventory_dependency_gates_preserve_known_zero_semantics() -> None:
    nonpositive = result(
        draft_value=draft(lines=(extracted_line(quantity=Decimal("0")),)),
        data=business_data(products=(product(available_quantity=None),)),
    )
    assert codes(nonpositive) == ["QUANTITY_NOT_POSITIVE"]
    assert issue(nonpositive, "QUANTITY_NOT_POSITIVE").actual == "0"

    unavailable = result(data=business_data(products=(product(available_quantity=None),)))
    assert codes(unavailable) == ["INVENTORY_UNAVAILABLE"]
    assert issue(unavailable, "INVENTORY_UNAVAILABLE").actual is None

    known_zero = result(data=business_data(products=(product(available_quantity=Decimal("0")),)))
    assert codes(known_zero) == ["INSUFFICIENT_INVENTORY"]
    assert issue(known_zero, "INSUFFICIENT_INVENTORY").actual == {
        "requested_quantity": "2",
        "available_quantity": "0",
    }


def test_price_required_negative_catalogue_and_currency_rules_are_gated() -> None:
    missing = result(
        draft_value=draft(lines=(extracted_line(submitted_price=None),)),
        data=business_data(products=(product(),)),
    )
    assert codes(missing) == ["SUBMITTED_PRICE_REQUIRED"]

    negative = result(
        draft_value=draft(lines=(extracted_line(submitted_price=Decimal("-1")),)),
        data=business_data(products=(product(),)),
    )
    assert codes(negative) == ["SUBMITTED_PRICE_NEGATIVE"]
    assert issue(negative, "SUBMITTED_PRICE_NEGATIVE").actual == "-1"

    unavailable = result(data=business_data(products=(product(catalogue_price=None),)))
    assert codes(unavailable) == ["CATALOGUE_PRICE_UNAVAILABLE"]
    assert issue(unavailable, "CATALOGUE_PRICE_UNAVAILABLE").actual is None

    mismatch = result(data=business_data(products=(product(currency="EUR"),)))
    assert codes(mismatch) == ["PRODUCT_CURRENCY_MISMATCH"]
    assert issue(mismatch, "PRODUCT_CURRENCY_MISMATCH").actual == {
        "product_currency": "EUR",
        "order_currency": "USD",
    }


@pytest.mark.parametrize(
    ("submitted_price", "expected_codes"),
    [
        (Decimal("10.90"), []),
        (Decimal("11.00"), []),
        (Decimal("11.01"), ["PRICE_OUTSIDE_TOLERANCE"]),
    ],
)
def test_price_tolerance_inside_boundary_and_outside(
    submitted_price: Decimal, expected_codes: list[str]
) -> None:
    value = result(
        draft_value=draft(lines=(extracted_line(submitted_price=submitted_price),)),
        data=business_data(products=(product(catalogue_price=Decimal("10")),)),
    )

    assert codes(value) == expected_codes
    if expected_codes:
        assert issue(value, "PRICE_OUTSIDE_TOLERANCE").actual == {
            "submitted_price": "11.01",
            "catalogue_price": "10",
            "difference": "1.01",
            "allowance": "1",
        }


def test_zero_catalogue_price_requires_exact_zero_submitted_price() -> None:
    valid = result(
        draft_value=draft(lines=(extracted_line(submitted_price=Decimal("0")),)),
        data=business_data(products=(product(catalogue_price=Decimal("0")),)),
    )
    assert codes(valid) == []

    invalid = result(
        draft_value=draft(lines=(extracted_line(submitted_price=Decimal("0.01")),)),
        data=business_data(products=(product(catalogue_price=Decimal("0")),)),
    )
    assert codes(invalid) == ["PRICE_OUTSIDE_TOLERANCE"]
    assert issue(invalid, "PRICE_OUTSIDE_TOLERANCE").actual == {
        "submitted_price": "0.01",
        "catalogue_price": "0",
        "difference": "0.01",
        "allowance": "0",
    }


def test_high_value_threshold_is_inclusive_and_warning_only() -> None:
    below = result(
        draft_value=draft(lines=(extracted_line(quantity=Decimal("9.999")),)),
        data=business_data(products=(product(),)),
    )
    assert below.order_total == Decimal("99.990")
    assert below.approval_level is ApprovalLevel.STANDARD
    assert codes(below) == []

    exact = result(
        draft_value=draft(lines=(extracted_line(quantity=Decimal("10")),)),
        data=business_data(products=(product(),)),
    )
    assert exact.order_total == Decimal("100")
    assert exact.issues == (
        type(issue(exact, "HIGH_VALUE_APPROVAL_REQUIRED"))(
            "HIGH_VALUE_APPROVAL_REQUIRED",
            ValidationSeverity.WARNING,
            "order_total",
            "total below the inclusive high-value threshold for standard approval",
            {"order_total": "100", "high_value_threshold": "100"},
            "Order total meets the high-value threshold and requires elevated approval.",
        ),
    )
    assert exact.route is ValidationRoute.READY_FOR_APPROVAL
    assert exact.approval_level is ApprovalLevel.ELEVATED
    assert exact.validated_order_data is not None


def test_high_value_warning_is_last_after_independent_line_issues() -> None:
    value = result(
        draft_value=draft(lines=(extracted_line(quantity=Decimal("10")),)),
        data=business_data(products=(product(available_quantity=Decimal("5")),)),
        validation_policy=policy(threshold=Decimal("100")),
    )

    assert codes(value) == ["INSUFFICIENT_INVENTORY", "HIGH_VALUE_APPROVAL_REQUIRED"]
    assert value.issues[-1].severity is ValidationSeverity.WARNING
    assert value.route is ValidationRoute.NEEDS_REVIEW
    assert value.validated_order_data is None


def test_multiple_violations_continue_independently_in_stable_matrix_order() -> None:
    value = result(
        draft_value=draft(
            customer_reference=None,
            customer_name=None,
            po_number=None,
            currency="GBP",
            lines=(
                extracted_line(sku=None, quantity=Decimal("0"), submitted_price=Decimal("-1")),
                extracted_line(sku="MISSING", quantity=None, submitted_price=None),
            ),
        ),
        data=TrustedBusinessData((customer(),), (None, None)),
    )

    assert codes(value) == [
        "CUSTOMER_REQUIRED",
        "PO_NUMBER_REQUIRED",
        "UNSUPPORTED_CURRENCY",
        "SKU_REQUIRED",
        "QUANTITY_NOT_POSITIVE",
        "SUBMITTED_PRICE_NEGATIVE",
        "UNKNOWN_SKU",
        "QUANTITY_REQUIRED",
        "SUBMITTED_PRICE_REQUIRED",
    ]
    assert all(item.severity is ValidationSeverity.ERROR for item in value.issues)
    assert value.route is ValidationRoute.NEEDS_REVIEW
    assert value.validated_order_data is None


def test_equal_five_inputs_produce_equal_complete_results() -> None:
    draft_value = draft(lines=(extracted_line(quantity=Decimal("10")),))
    data = business_data(products=(product(),))
    validation_facts = facts()
    validation_policy = policy()
    validation_context = context()

    first = validate(draft_value, data, validation_facts, validation_policy, validation_context)
    second = validate(draft_value, data, validation_facts, validation_policy, validation_context)

    assert first == second
    assert first.issues == second.issues
    assert first.order_total == second.order_total
    assert first.approval_level is second.approval_level
    assert first.route is second.route
    assert first.validated_order_data == second.validated_order_data


def _approved_sync_order(
    *,
    submitted_price: Decimal = Decimal("10"),
    currency: str = "USD",
) -> Order:
    return Order(
        id=uuid4(),
        customer_reference="CUST-001",
        po_number="PO-1001",
        order_date=date(2026, 9, 1),
        requested_delivery_date=date(2026, 9, 20),
        currency=currency,
        lines=(
            OrderLine(
                id=uuid4(),
                sku="SKU-001",
                description="Approved widget",
                quantity=Decimal("2"),
                submitted_price=submitted_price,
                trusted_catalogue_price=Decimal("10"),
            ),
        ),
        state=OrderState.SYNCING,
    )


def test_preflight_rejects_missing_or_inactive_customer_and_product() -> None:
    sync_policy = build_demo_review_runtime().policy
    order = _approved_sync_order()

    cases = (
        (TrustedBusinessData((), (product(),)), "UNKNOWN_CUSTOMER"),
        (
            TrustedBusinessData((customer(active=False),), (product(),)),
            "INACTIVE_CUSTOMER",
        ),
        (TrustedBusinessData((customer(),), (None,)), "UNKNOWN_SKU"),
        (
            TrustedBusinessData((customer(),), (product(active=False),)),
            "INACTIVE_SKU",
        ),
    )
    for trusted_data, expected_code in cases:
        issues = approved_order_trusted_data_issues(order, trusted_data, sync_policy)
        assert expected_code in {item.rule_code for item in issues}


def test_preflight_rejects_currency_price_and_inventory_mismatch() -> None:
    sync_policy = build_demo_review_runtime().policy
    order = _approved_sync_order()
    cases = (
        (product(currency="EUR"), "PRODUCT_CURRENCY_MISMATCH"),
        (product(catalogue_price=Decimal("20")), "PRICE_OUTSIDE_TOLERANCE"),
        (product(available_quantity=Decimal("1")), "INSUFFICIENT_INVENTORY"),
    )

    for trusted_product, expected_code in cases:
        data = TrustedBusinessData((customer(),), (trusted_product,))
        issues = approved_order_trusted_data_issues(order, data, sync_policy)
        assert expected_code in {item.rule_code for item in issues}


def test_preflight_reuses_existing_five_percent_policy() -> None:
    sync_policy = build_demo_review_runtime().policy
    data = business_data()

    within = approved_order_trusted_data_issues(
        _approved_sync_order(submitted_price=Decimal("10.5")), data, sync_policy
    )
    outside = approved_order_trusted_data_issues(
        _approved_sync_order(submitted_price=Decimal("10.51")), data, sync_policy
    )

    assert "PRICE_OUTSIDE_TOLERANCE" not in {item.rule_code for item in within}
    assert "PRICE_OUTSIDE_TOLERANCE" in {item.rule_code for item in outside}


def test_sync_preflight_does_not_rerun_intake_routing_or_mutate_order() -> None:
    sync_policy = build_demo_review_runtime().policy
    order = _approved_sync_order()
    trusted_data = business_data()

    issues = approved_order_trusted_data_issues(order, trusted_data, sync_policy)

    assert issues == ()
    assert order.state is OrderState.SYNCING
    assert order.po_number == "PO-1001"
    assert order.requested_delivery_date == date(2026, 9, 20)
