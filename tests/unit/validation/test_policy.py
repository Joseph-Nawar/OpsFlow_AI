from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from opsflow.validation.policy import ValidationPolicy


def policy(**overrides: object) -> ValidationPolicy:
    values: dict[str, object] = {
        "supported_currencies": ("EUR", "USD", "GBP"),
        "price_tolerance_fraction": Decimal("0.05"),
        "high_value_threshold": Decimal("1000"),
    }
    values.update(overrides)
    return ValidationPolicy(**values)


def test_policy_preserves_caller_currency_order_and_is_immutable() -> None:
    currencies = ("JPY", "USD", "EUR")
    value = policy(supported_currencies=currencies)

    assert value.supported_currencies == currencies
    assert value.price_tolerance_fraction == Decimal("0.05")
    assert value.high_value_threshold == Decimal("1000")
    with pytest.raises(FrozenInstanceError):
        value.high_value_threshold = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize("currencies", [(), ("USD", "USD"), ("usd",), ("US",), ("USDE",)])
def test_policy_rejects_empty_duplicate_or_malformed_currency_codes(
    currencies: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        policy(supported_currencies=currencies)


@pytest.mark.parametrize("currencies", [["USD"], ["USD", "EUR"]])
def test_policy_rejects_mutable_currency_collections(currencies: list[str]) -> None:
    with pytest.raises(ValueError):
        policy(supported_currencies=currencies)


@pytest.mark.parametrize("bad_value", [0.05, 5, Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
def test_policy_rejects_invalid_tolerance(bad_value: object) -> None:
    with pytest.raises(ValueError):
        policy(price_tolerance_fraction=bad_value)


@pytest.mark.parametrize("bad_value", [0.05, 5, Decimal("NaN"), Decimal("-0.01")])
def test_policy_rejects_invalid_high_value_threshold(bad_value: object) -> None:
    with pytest.raises(ValueError):
        policy(high_value_threshold=bad_value)


def test_policy_accepts_zero_and_finite_decimal_boundaries() -> None:
    value = policy(
        supported_currencies=("USD",),
        price_tolerance_fraction=Decimal("0"),
        high_value_threshold=Decimal("0"),
    )

    assert value.price_tolerance_fraction == Decimal("0")
    assert value.high_value_threshold == Decimal("0")


def test_policy_has_no_implicit_default_values() -> None:
    with pytest.raises(TypeError):
        ValidationPolicy()  # type: ignore[call-arg]
