"""Phase 6 synthetic runtime composition tests."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from opsflow.main import create_app
from opsflow.review.composition import (
    ReviewRuntime,
    SystemReviewDateProvider,
    build_demo_review_runtime,
)
from opsflow.settings import DevelopmentOperatorConfig, Settings
from opsflow.validation import BusinessDataLookupRequest, TrustedBusinessData
from opsflow.validation.policy import ValidationPolicy
from opsflow.validation.sandbox import SandboxBusinessDataProvider


def test_demo_runtime_composes_exact_synthetic_policy_and_customer_data() -> None:
    runtime = build_demo_review_runtime()

    assert runtime.policy == ValidationPolicy(
        supported_currencies=("USD",),
        price_tolerance_fraction=Decimal("0.05"),
        high_value_threshold=Decimal("1000"),
    )
    assert isinstance(runtime.provider, SandboxBusinessDataProvider)
    # SandboxBusinessDataProvider stores customers in stable reference order.
    assert tuple(
        (customer.reference, customer.name, customer.active)
        for customer in runtime.provider.customers
    ) == (
        ("CUST-001", "Acme Industries", True),
        ("CUST-002", "Northstar Retail", True),
        ("CUST-003", "Inactive Industries", False),
    )


def test_demo_provider_is_network_free_and_has_exact_decimal_products() -> None:
    runtime = build_demo_review_runtime()
    products = runtime.provider.products

    assert tuple(
        (
            product.sku,
            product.description,
            product.active,
            product.currency,
            product.catalogue_price,
            product.available_quantity,
        )
        for product in products
    ) == (
        ("SKU-001", "Widget", True, "USD", Decimal("10"), Decimal("100")),
        ("SKU-002", "Gadget", True, "USD", Decimal("25"), Decimal("10")),
        ("SKU-003", "Legacy Widget", False, "USD", Decimal("5"), Decimal("0")),
    )

    result = asyncio.run(
        runtime.provider.get_validation_data(
            BusinessDataLookupRequest("CUST-001", None, ("SKU-001", "SKU-003"))
        )
    )

    assert isinstance(result, TrustedBusinessData)
    assert tuple(item.reference for item in result.customer_candidates) == ("CUST-001",)
    assert tuple(item.sku if item is not None else None for item in result.products_by_line) == (
        "SKU-001",
        "SKU-003",
    )


def test_demo_runtime_exposes_one_injectable_current_date_provider() -> None:
    runtime = build_demo_review_runtime()

    assert isinstance(runtime.date_provider, SystemReviewDateProvider)
    assert type(runtime.date_provider.current_date()) is date


def test_runtime_accepts_explicit_policy_provider_and_fixed_date_without_settings() -> None:
    original = build_demo_review_runtime()
    policy = ValidationPolicy(("CAD",), Decimal("0.10"), Decimal("500"))
    provider = SandboxBusinessDataProvider((), ())

    class FixedDateProvider:
        def current_date(self) -> date:
            return date(2031, 2, 3)

    injected = ReviewRuntime(policy, provider, FixedDateProvider())

    assert injected.policy is policy
    assert injected.provider is provider
    assert injected.date_provider.current_date() == date(2031, 2, 3)
    with pytest.raises(FrozenInstanceError):
        injected.policy = original.policy  # type: ignore[misc]


def test_fastapi_composition_stores_runtime_and_configured_operators_on_app_state() -> None:
    operator = DevelopmentOperatorConfig(
        token="fake-app-state-credential", actor="reviewer-app", role="REVIEWER"
    )
    app = create_app(Settings(_env_file=None, review_dev_operators=(operator,)))

    assert isinstance(app.state.review_runtime, ReviewRuntime)
    assert app.state.review_dev_operators == (operator,)
    asyncio.run(app.state.database_engine.dispose())
