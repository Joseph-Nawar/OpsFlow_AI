"""Explicit synthetic Phase 6 policy, provider, and review-date composition."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from opsflow.validation.business_data import BusinessDataProvider
from opsflow.validation.models import TrustedCustomer, TrustedProduct
from opsflow.validation.policy import ValidationPolicy
from opsflow.validation.sandbox import SandboxBusinessDataProvider


class ReviewDateProvider(Protocol):
    """Injectable source for the review-time evaluation date."""

    def current_date(self) -> date:
        """Return one current calendar date for a review command."""


@dataclass(frozen=True, slots=True)
class SystemReviewDateProvider:
    """Development date source; deterministic services receive the captured value."""

    def current_date(self) -> date:
        """Return the local calendar date at the point the command begins."""

        return date.today()


@dataclass(frozen=True, slots=True)
class ReviewRuntime:
    """Application-composed deterministic policy and trusted lookup dependencies."""

    policy: ValidationPolicy
    provider: BusinessDataProvider
    date_provider: ReviewDateProvider


def build_demo_review_runtime() -> ReviewRuntime:
    """Build the exact network-free synthetic business data runtime for Phase 6."""

    policy = ValidationPolicy(
        supported_currencies=("USD",),
        price_tolerance_fraction=Decimal("0.05"),
        high_value_threshold=Decimal("1000"),
    )
    provider = SandboxBusinessDataProvider(
        customers=(
            TrustedCustomer("CUST-001", "Acme Industries", True),
            TrustedCustomer("CUST-002", "Northstar Retail", True),
            TrustedCustomer("CUST-003", "Inactive Industries", False),
        ),
        products=(
            TrustedProduct("SKU-001", "Widget", True, "USD", Decimal("10"), Decimal("100")),
            TrustedProduct("SKU-002", "Gadget", True, "USD", Decimal("25"), Decimal("10")),
            TrustedProduct("SKU-003", "Legacy Widget", False, "USD", Decimal("5"), Decimal("0")),
        ),
    )
    return ReviewRuntime(
        policy=policy,
        provider=provider,
        date_provider=SystemReviewDateProvider(),
    )
