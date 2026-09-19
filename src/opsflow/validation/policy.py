"""Explicit immutable policy for deterministic Phase 5 validation."""

import re
from dataclasses import dataclass
from decimal import Decimal

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}", flags=re.ASCII)


def _require_nonnegative_decimal(name: str, value: object) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    """All policy values required for one validation evaluation."""

    supported_currencies: tuple[str, ...]
    price_tolerance_fraction: Decimal
    high_value_threshold: Decimal

    def __post_init__(self) -> None:
        if type(self.supported_currencies) is not tuple or not self.supported_currencies:
            raise ValueError("supported_currencies must be a non-empty tuple")
        for currency in self.supported_currencies:
            if not isinstance(currency, str) or _CURRENCY_PATTERN.fullmatch(currency) is None:
                raise ValueError("supported_currencies must contain uppercase ASCII 3-letter codes")
        if len(set(self.supported_currencies)) != len(self.supported_currencies):
            raise ValueError("supported_currencies must contain unique codes")
        _require_nonnegative_decimal("price_tolerance_fraction", self.price_tolerance_fraction)
        _require_nonnegative_decimal("high_value_threshold", self.high_value_threshold)
