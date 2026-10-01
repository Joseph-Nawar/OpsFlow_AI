"""Pure, synchronous, deterministic Phase 5 validation engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from opsflow.domain import Order, OrderState, ValidationIssue, ValidationSeverity
from opsflow.validation.models import (
    ApprovalLevel,
    TrustedBusinessData,
    TrustedCustomer,
    ValidatedOrderData,
    ValidatedOrderLine,
    ValidationContext,
    ValidationFacts,
    ValidationResult,
    ValidationRoute,
)
from opsflow.validation.policy import ValidationPolicy

if TYPE_CHECKING:
    from opsflow.extraction.models import ExtractionDraft


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _date_text(value: date) -> str:
    return value.isoformat()


def _price_within_tolerance(
    submitted_price: Decimal,
    catalogue_price: Decimal,
    policy: ValidationPolicy,
) -> bool:
    difference = abs(submitted_price - catalogue_price)
    allowance = abs(catalogue_price) * policy.price_tolerance_fraction
    return difference <= allowance


def _add_issue(
    issues: list[ValidationIssue],
    rule_code: str,
    field: str,
    expected: object,
    actual: object,
    explanation: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
) -> None:
    issues.append(ValidationIssue(rule_code, severity, field, expected, actual, explanation))


def _compute_total(draft: ExtractionDraft) -> Decimal | None:
    if not draft.lines:
        return None
    total = Decimal("0")
    for line in draft.lines:
        if (
            line.quantity is None
            or line.quantity <= 0
            or line.submitted_price is None
            or line.submitted_price < 0
        ):
            return None
        total += line.quantity * line.submitted_price
    return total


def _append_customer_issues(
    issues: list[ValidationIssue],
    draft: ExtractionDraft,
    data: TrustedBusinessData,
) -> TrustedCustomer | None:
    if draft.customer_reference is None and draft.customer_name is None:
        _add_issue(
            issues,
            "CUSTOMER_REQUIRED",
            "customer",
            "customer_reference or customer_name",
            None,
            "Customer reference or customer name is required.",
        )
        return None

    field = "customer_reference" if draft.customer_reference is not None else "customer_name"
    identity = (
        draft.customer_reference if draft.customer_reference is not None else draft.customer_name
    )
    candidates = data.customer_candidates
    if not candidates:
        _add_issue(
            issues,
            "UNKNOWN_CUSTOMER",
            field,
            "one exact trusted customer",
            identity,
            "No exact trusted customer matched the supplied identity.",
        )
        return None
    if len(candidates) > 1:
        _add_issue(
            issues,
            "AMBIGUOUS_CUSTOMER",
            field,
            "one exact trusted customer",
            {"identity": identity, "candidate_count": len(candidates)},
            "Multiple exact trusted customers matched the supplied identity.",
        )
        return None

    candidate = candidates[0]
    if not candidate.active:
        _add_issue(
            issues,
            "INACTIVE_CUSTOMER",
            field,
            "active trusted customer",
            candidate.reference,
            "The matched customer is inactive.",
        )
        return None
    return candidate


def _append_line_issues(
    issues: list[ValidationIssue],
    draft: ExtractionDraft,
    data: TrustedBusinessData,
    policy: ValidationPolicy,
) -> None:
    usable_currency = draft.currency if draft.currency in policy.supported_currencies else None

    for index, line in enumerate(draft.lines):
        field_prefix = f"lines[{index}]"
        if line.sku is None:
            _add_issue(
                issues,
                "SKU_REQUIRED",
                f"{field_prefix}.sku",
                "non-null SKU",
                None,
                f"SKU is required for line {index}.",
            )
            product = None
        else:
            product = data.products_by_line[index]
            if product is None:
                _add_issue(
                    issues,
                    "UNKNOWN_SKU",
                    f"{field_prefix}.sku",
                    "one exact trusted product",
                    line.sku,
                    f"SKU is not present in trusted product data for line {index}.",
                )
            elif not product.active:
                _add_issue(
                    issues,
                    "INACTIVE_SKU",
                    f"{field_prefix}.sku",
                    "active trusted product",
                    line.sku,
                    f"SKU refers to an inactive trusted product on line {index}.",
                )

        if line.quantity is None:
            _add_issue(
                issues,
                "QUANTITY_REQUIRED",
                f"{field_prefix}.quantity",
                "non-null quantity",
                None,
                f"Quantity is required for line {index}.",
            )
        elif line.quantity <= 0:
            _add_issue(
                issues,
                "QUANTITY_NOT_POSITIVE",
                f"{field_prefix}.quantity",
                "quantity greater than zero",
                _decimal_text(line.quantity),
                f"Quantity must be greater than zero for line {index}.",
            )
        elif product is not None:
            if product.available_quantity is None:
                _add_issue(
                    issues,
                    "INVENTORY_UNAVAILABLE",
                    f"{field_prefix}.quantity",
                    "known trusted available quantity",
                    None,
                    f"Trusted inventory availability is unavailable for line {index}.",
                )
            elif line.quantity > product.available_quantity:
                _add_issue(
                    issues,
                    "INSUFFICIENT_INVENTORY",
                    f"{field_prefix}.quantity",
                    "requested quantity <= trusted available quantity",
                    {
                        "requested_quantity": _decimal_text(line.quantity),
                        "available_quantity": _decimal_text(product.available_quantity),
                    },
                    f"Requested quantity exceeds trusted available inventory for line {index}.",
                )

        if line.submitted_price is None:
            _add_issue(
                issues,
                "SUBMITTED_PRICE_REQUIRED",
                f"{field_prefix}.submitted_price",
                "non-null submitted price",
                None,
                f"Submitted price is required for line {index}.",
            )
        elif line.submitted_price < 0:
            _add_issue(
                issues,
                "SUBMITTED_PRICE_NEGATIVE",
                f"{field_prefix}.submitted_price",
                "price greater than or equal to zero",
                _decimal_text(line.submitted_price),
                f"Submitted price must not be negative for line {index}.",
            )

        if product is None:
            continue

        if product.catalogue_price is None:
            _add_issue(
                issues,
                "CATALOGUE_PRICE_UNAVAILABLE",
                f"{field_prefix}.submitted_price",
                "trusted catalogue price",
                None,
                f"Trusted catalogue price is unavailable for line {index}.",
            )

        if usable_currency is not None and product.currency != usable_currency:
            _add_issue(
                issues,
                "PRODUCT_CURRENCY_MISMATCH",
                f"{field_prefix}.sku",
                "trusted product currency equal to the usable order currency",
                {"product_currency": product.currency, "order_currency": usable_currency},
                f"Product currency does not match order currency for line {index}.",
            )

        if (
            product.catalogue_price is None
            or line.submitted_price is None
            or line.submitted_price < 0
            or usable_currency is None
            or product.currency != usable_currency
        ):
            continue

        if not _price_within_tolerance(line.submitted_price, product.catalogue_price, policy):
            difference = abs(line.submitted_price - product.catalogue_price)
            allowance = abs(product.catalogue_price) * policy.price_tolerance_fraction
            _add_issue(
                issues,
                "PRICE_OUTSIDE_TOLERANCE",
                f"{field_prefix}.submitted_price",
                "absolute difference no greater than the Decimal tolerance allowance",
                {
                    "submitted_price": _decimal_text(line.submitted_price),
                    "catalogue_price": _decimal_text(product.catalogue_price),
                    "difference": _decimal_text(difference),
                    "allowance": _decimal_text(allowance),
                },
                (
                    "Submitted price is outside the configured catalogue-price tolerance "
                    f"for line {index}."
                ),
            )


def approved_order_trusted_data_issues(
    order: Order,
    data: TrustedBusinessData,
    policy: ValidationPolicy,
) -> tuple[ValidationIssue, ...]:
    """Recheck only trusted customer/product facts for an approved sync order."""

    if order.state not in {OrderState.APPROVED, OrderState.SYNCING}:
        raise ValueError("trusted-data preflight requires an approved or syncing order")
    if len(data.products_by_line) != len(order.lines):
        raise ValueError("trusted products must match the approved order line count")

    issues: list[ValidationIssue] = []
    customer: TrustedCustomer | None = None
    if order.customer_reference is None:
        _add_issue(
            issues,
            "CUSTOMER_REQUIRED",
            "customer_reference",
            "exact trusted customer reference",
            None,
            "An approved order has no trusted customer reference.",
        )
    else:
        matching_customers = tuple(
            candidate
            for candidate in data.customer_candidates
            if candidate.reference == order.customer_reference
        )
        if not matching_customers:
            _add_issue(
                issues,
                "UNKNOWN_CUSTOMER",
                "customer_reference",
                "one exact trusted customer",
                order.customer_reference,
                "No exact trusted customer matched the approved order.",
            )
        elif len(matching_customers) > 1:
            _add_issue(
                issues,
                "AMBIGUOUS_CUSTOMER",
                "customer_reference",
                "one exact trusted customer",
                order.customer_reference,
                "Multiple exact trusted customers matched the approved order.",
            )
        else:
            customer = matching_customers[0]
            if not customer.active:
                _add_issue(
                    issues,
                    "INACTIVE_CUSTOMER",
                    "customer_reference",
                    "active trusted customer",
                    order.customer_reference,
                    "The trusted customer is no longer eligible.",
                )

    if order.currency is None:
        _add_issue(
            issues,
            "CURRENCY_REQUIRED",
            "currency",
            "supported order currency",
            None,
            "An approved order has no currency.",
        )
    elif order.currency not in policy.supported_currencies:
        _add_issue(
            issues,
            "UNSUPPORTED_CURRENCY",
            "currency",
            list(policy.supported_currencies),
            order.currency,
            "The approved order currency is not supported by policy.",
        )

    for index, (line, product) in enumerate(zip(order.lines, data.products_by_line, strict=True)):
        field_prefix = f"lines[{index}]"
        if line.sku is None:
            _add_issue(
                issues,
                "SKU_REQUIRED",
                f"{field_prefix}.sku",
                "non-null SKU",
                None,
                "The approved line has no SKU.",
            )
            continue
        if product is None:
            _add_issue(
                issues,
                "UNKNOWN_SKU",
                f"{field_prefix}.sku",
                "one exact trusted product",
                line.sku,
                "The SKU is no longer present in trusted product data.",
            )
            continue
        if product.sku != line.sku:
            _add_issue(
                issues,
                "UNKNOWN_SKU",
                f"{field_prefix}.sku",
                line.sku,
                product.sku,
                "The trusted product does not match the approved SKU.",
            )
            continue
        if not product.active:
            _add_issue(
                issues,
                "INACTIVE_SKU",
                f"{field_prefix}.sku",
                "active trusted product",
                line.sku,
                "The trusted product is no longer eligible.",
            )
        if product.available_quantity is None:
            _add_issue(
                issues,
                "INVENTORY_UNAVAILABLE",
                f"{field_prefix}.quantity",
                "known trusted available quantity",
                None,
                "Trusted inventory availability is unavailable.",
            )
        elif line.quantity > product.available_quantity:
            _add_issue(
                issues,
                "INSUFFICIENT_INVENTORY",
                f"{field_prefix}.quantity",
                "requested quantity <= trusted available quantity",
                line.quantity,
                "Requested quantity exceeds trusted available inventory.",
            )
        if order.currency is not None and product.currency != order.currency:
            _add_issue(
                issues,
                "PRODUCT_CURRENCY_MISMATCH",
                f"{field_prefix}.sku",
                order.currency,
                product.currency,
                "Trusted product currency no longer matches the approved order.",
            )
        if product.catalogue_price is None:
            _add_issue(
                issues,
                "CATALOGUE_PRICE_UNAVAILABLE",
                f"{field_prefix}.submitted_price",
                "trusted catalogue price",
                None,
                "Trusted catalogue price is unavailable.",
            )
        elif (
            line.submitted_price is not None
            and line.submitted_price >= 0
            and order.currency in policy.supported_currencies
            and product.currency == order.currency
            and not _price_within_tolerance(line.submitted_price, product.catalogue_price, policy)
        ):
            _add_issue(
                issues,
                "PRICE_OUTSIDE_TOLERANCE",
                f"{field_prefix}.submitted_price",
                "absolute difference within configured catalogue-price tolerance",
                line.submitted_price,
                "Approved submitted price is outside the current trusted-price tolerance.",
            )

    return tuple(issues)


def _build_validated_data(
    draft: ExtractionDraft,
    data: TrustedBusinessData,
    customer: TrustedCustomer | None,
) -> ValidatedOrderData | None:
    if (
        customer is None
        or draft.po_number is None
        or draft.order_date is None
        or draft.requested_delivery_date is None
        or draft.currency is None
    ):
        return None

    lines: list[ValidatedOrderLine] = []
    for index, extracted in enumerate(draft.lines):
        product = data.products_by_line[index]
        if (
            extracted.sku is None
            or product is None
            or not product.active
            or extracted.quantity is None
            or extracted.quantity <= 0
            or extracted.submitted_price is None
            or extracted.submitted_price < 0
            or product.catalogue_price is None
            or product.available_quantity is None
            or extracted.quantity > product.available_quantity
            or product.currency != draft.currency
        ):
            return None
        lines.append(
            ValidatedOrderLine(
                sku=product.sku,
                description=product.description or extracted.description,
                quantity=extracted.quantity,
                submitted_price=extracted.submitted_price,
                trusted_catalogue_price=product.catalogue_price,
            )
        )
    if not lines:
        return None
    return ValidatedOrderData(
        customer_reference=customer.reference,
        po_number=draft.po_number,
        order_date=draft.order_date,
        requested_delivery_date=draft.requested_delivery_date,
        currency=draft.currency,
        lines=tuple(lines),
    )


def validate(
    draft: ExtractionDraft,
    trusted_business_data: TrustedBusinessData,
    validation_facts: ValidationFacts,
    policy: ValidationPolicy,
    context: ValidationContext,
) -> ValidationResult:
    """Evaluate the complete deterministic Phase 5 rule matrix."""

    if len(trusted_business_data.products_by_line) != len(draft.lines):
        raise ValueError("trusted products must match the draft line count")

    issues: list[ValidationIssue] = []
    matched_customer = _append_customer_issues(issues, draft, trusted_business_data)

    if draft.po_number is None:
        _add_issue(
            issues,
            "PO_NUMBER_REQUIRED",
            "po_number",
            "non-null PO number",
            None,
            "Purchase-order number is required.",
        )
    elif matched_customer is not None and validation_facts.duplicate_customer_po:
        _add_issue(
            issues,
            "DUPLICATE_CUSTOMER_PO",
            "po_number",
            "no existing exact customer+PO pair",
            {"customer_reference": matched_customer.reference, "po_number": draft.po_number},
            "The customer-scoped purchase-order reference already exists.",
        )

    if validation_facts.document_already_processed:
        _add_issue(
            issues,
            "DOCUMENT_ALREADY_PROCESSED",
            "source_sha256",
            "no earlier processed snapshot for this SHA-256",
            draft.source_sha256,
            "The source document SHA-256 was already processed under another order or source.",
        )

    if draft.order_date is None:
        _add_issue(
            issues,
            "ORDER_DATE_REQUIRED",
            "order_date",
            "a date",
            None,
            "Order date is required.",
        )
    elif draft.order_date > context.evaluation_date:
        _add_issue(
            issues,
            "ORDER_DATE_IN_FUTURE",
            "order_date",
            "order_date <= evaluation_date",
            {
                "order_date": _date_text(draft.order_date),
                "evaluation_date": _date_text(context.evaluation_date),
            },
            "Order date is later than the evaluation date.",
        )

    if draft.requested_delivery_date is None:
        _add_issue(
            issues,
            "DELIVERY_DATE_REQUIRED",
            "requested_delivery_date",
            "a requested delivery date",
            None,
            "Requested delivery date is required.",
        )
    else:
        if draft.requested_delivery_date < context.evaluation_date:
            _add_issue(
                issues,
                "DELIVERY_DATE_IN_PAST",
                "requested_delivery_date",
                "requested_delivery_date >= evaluation_date",
                {
                    "requested_delivery_date": _date_text(draft.requested_delivery_date),
                    "evaluation_date": _date_text(context.evaluation_date),
                },
                "Requested delivery date is earlier than the evaluation date.",
            )
        if draft.order_date is not None and draft.requested_delivery_date < draft.order_date:
            _add_issue(
                issues,
                "DELIVERY_BEFORE_ORDER_DATE",
                "requested_delivery_date",
                "requested_delivery_date >= order_date",
                {
                    "order_date": _date_text(draft.order_date),
                    "requested_delivery_date": _date_text(draft.requested_delivery_date),
                },
                "Requested delivery date is earlier than the order date.",
            )

    if draft.currency is None:
        _add_issue(
            issues,
            "CURRENCY_REQUIRED",
            "currency",
            "non-null currency",
            None,
            "Currency is required.",
        )
    elif draft.currency not in policy.supported_currencies:
        _add_issue(
            issues,
            "UNSUPPORTED_CURRENCY",
            "currency",
            list(policy.supported_currencies),
            draft.currency,
            "Currency is not supported by the explicit validation policy.",
        )

    if not draft.lines:
        _add_issue(
            issues,
            "ORDER_LINES_REQUIRED",
            "lines",
            "at least one line",
            [],
            "At least one order line is required.",
        )
    else:
        _append_line_issues(issues, draft, trusted_business_data, policy)

    total = _compute_total(draft)
    approval_level = ApprovalLevel.STANDARD
    if total is not None and total >= policy.high_value_threshold:
        approval_level = ApprovalLevel.ELEVATED
        _add_issue(
            issues,
            "HIGH_VALUE_APPROVAL_REQUIRED",
            "order_total",
            "total below the inclusive high-value threshold for standard approval",
            {
                "order_total": _decimal_text(total),
                "high_value_threshold": _decimal_text(policy.high_value_threshold),
            },
            "Order total meets the high-value threshold and requires elevated approval.",
            severity=ValidationSeverity.WARNING,
        )

    has_error = any(item.severity is ValidationSeverity.ERROR for item in issues)
    route = ValidationRoute.NEEDS_REVIEW if has_error else ValidationRoute.READY_FOR_APPROVAL
    validated_data = (
        None if has_error else _build_validated_data(draft, trusted_business_data, matched_customer)
    )

    return ValidationResult(
        issues=tuple(issues),
        route=route,
        approval_level=approval_level,
        order_total=total,
        validated_order_data=validated_data,
    )
