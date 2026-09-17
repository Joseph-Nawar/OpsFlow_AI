"""Immutable value contracts for deterministic Phase 5 validation."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from opsflow.domain import ValidationIssue, ValidationSeverity

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}", flags=re.ASCII)


def _require_non_blank(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


def _require_optional_string(name: str, value: object) -> None:
    if value is not None:
        _require_non_blank(name, value)


def _require_currency(name: str, value: object) -> None:
    if not isinstance(value, str) or _CURRENCY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be an uppercase ASCII 3-letter currency")


def _require_nonnegative_optional_decimal(name: str, value: object) -> None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
        raise ValueError(f"{name} must be a finite Decimal or None")
    if isinstance(value, Decimal) and value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _require_nonnegative_decimal(name: str, value: object) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _require_date(name: str, value: object) -> None:
    if type(value) is not date:
        raise ValueError(f"{name} must be a date")


def _require_optional_date(name: str, value: object) -> None:
    if value is not None:
        _require_date(name, value)


def _require_tuple(name: str, value: object) -> None:
    if type(value) is not tuple:
        raise ValueError(f"{name} must be an immutable tuple")


class ValidationRoute(Enum):
    """Deterministic workflow route derived from validation severity."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"


class ApprovalLevel(Enum):
    """Approval policy classification carried by an in-memory result."""

    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Explicit date context for one deterministic validation evaluation."""

    evaluation_date: date

    def __post_init__(self) -> None:
        _require_date("evaluation_date", self.evaluation_date)


@dataclass(frozen=True, slots=True)
class ValidationFacts:
    """Immutable OpsFlow-local facts supplied separately from reference data."""

    duplicate_customer_po: bool
    document_already_processed: bool

    def __post_init__(self) -> None:
        if type(self.duplicate_customer_po) is not bool:
            raise ValueError("duplicate_customer_po must be a bool")
        if type(self.document_already_processed) is not bool:
            raise ValueError("document_already_processed must be a bool")


@dataclass(frozen=True, slots=True)
class TrustedCustomer:
    """One externally sourced trusted customer reference record."""

    reference: str
    name: str
    active: bool

    def __post_init__(self) -> None:
        _require_non_blank("reference", self.reference)
        _require_non_blank("name", self.name)
        if type(self.active) is not bool:
            raise ValueError("active must be a bool")


@dataclass(frozen=True, slots=True)
class TrustedProduct:
    """One externally sourced trusted product reference record."""

    sku: str
    description: str | None
    active: bool
    currency: str
    catalogue_price: Decimal | None
    available_quantity: Decimal | None

    def __post_init__(self) -> None:
        _require_non_blank("sku", self.sku)
        _require_optional_string("description", self.description)
        if type(self.active) is not bool:
            raise ValueError("active must be a bool")
        _require_currency("currency", self.currency)
        _require_nonnegative_optional_decimal("catalogue_price", self.catalogue_price)
        _require_nonnegative_optional_decimal("available_quantity", self.available_quantity)


@dataclass(frozen=True, slots=True)
class TrustedBusinessData:
    """External trusted customer/product reference data for one draft."""

    customer_candidates: tuple[TrustedCustomer, ...]
    products_by_line: tuple[TrustedProduct | None, ...]

    def __post_init__(self) -> None:
        _require_tuple("customer_candidates", self.customer_candidates)
        if not all(isinstance(item, TrustedCustomer) for item in self.customer_candidates):
            raise ValueError("customer_candidates must contain TrustedCustomer values")
        _require_tuple("products_by_line", self.products_by_line)
        if not all(
            item is None or isinstance(item, TrustedProduct) for item in self.products_by_line
        ):
            raise ValueError("products_by_line must contain TrustedProduct values or None")


@dataclass(frozen=True, slots=True)
class BusinessDataLookupRequest:
    """External reference-data lookup inputs derived from an extraction draft."""

    customer_reference: str | None
    customer_name: str | None
    skus: tuple[str | None, ...]

    def __post_init__(self) -> None:
        _require_optional_string("customer_reference", self.customer_reference)
        _require_optional_string("customer_name", self.customer_name)
        _require_tuple("skus", self.skus)
        for sku in self.skus:
            _require_optional_string("sku", sku)


@dataclass(frozen=True, slots=True)
class ValidatedOrderLine:
    """One trusted, promotable order line produced by the engine."""

    sku: str
    description: str | None
    quantity: Decimal
    submitted_price: Decimal
    trusted_catalogue_price: Decimal

    def __post_init__(self) -> None:
        _require_non_blank("sku", self.sku)
        _require_optional_string("description", self.description)
        _require_nonnegative_decimal("quantity", self.quantity)
        if self.quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        _require_nonnegative_decimal("submitted_price", self.submitted_price)
        _require_nonnegative_decimal("trusted_catalogue_price", self.trusted_catalogue_price)


@dataclass(frozen=True, slots=True)
class ValidatedOrderData:
    """Complete trusted order data safe for later domain promotion."""

    customer_reference: str
    po_number: str
    order_date: date
    requested_delivery_date: date
    currency: str
    lines: tuple[ValidatedOrderLine, ...]

    def __post_init__(self) -> None:
        _require_non_blank("customer_reference", self.customer_reference)
        _require_non_blank("po_number", self.po_number)
        _require_date("order_date", self.order_date)
        _require_date("requested_delivery_date", self.requested_delivery_date)
        _require_currency("currency", self.currency)
        _require_tuple("lines", self.lines)
        if not self.lines or not all(isinstance(line, ValidatedOrderLine) for line in self.lines):
            raise ValueError("lines must be a non-empty tuple of ValidatedOrderLine")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Immutable output of the complete deterministic validation engine."""

    issues: tuple[ValidationIssue, ...]
    route: ValidationRoute
    approval_level: ApprovalLevel
    order_total: Decimal | None
    validated_order_data: ValidatedOrderData | None

    def __post_init__(self) -> None:
        _require_tuple("issues", self.issues)
        if not all(isinstance(issue, ValidationIssue) for issue in self.issues):
            raise ValueError("issues must contain ValidationIssue values")
        if not isinstance(self.route, ValidationRoute):
            raise ValueError("route must be a ValidationRoute")
        if not isinstance(self.approval_level, ApprovalLevel):
            raise ValueError("approval_level must be an ApprovalLevel")
        _require_nonnegative_optional_decimal("order_total", self.order_total)
        if self.validated_order_data is not None and not isinstance(
            self.validated_order_data, ValidatedOrderData
        ):
            raise ValueError("validated_order_data must be ValidatedOrderData or None")
        if any(issue.severity is ValidationSeverity.ERROR for issue in self.issues) and (
            self.validated_order_data is not None
        ):
            raise ValueError("blocking validation results cannot carry promotable data")
