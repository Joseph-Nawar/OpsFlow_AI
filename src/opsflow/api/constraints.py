"""Small reusable Pydantic constraints for client-controlled transport values."""

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field

MAX_DECIMAL_DIGITS = 28
MAX_DECIMAL_FRACTIONAL_DIGITS = 8


def validate_transport_decimal(value: Decimal) -> Decimal:
    """Reject non-finite or resource-expanding client decimal representations."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("decimal must be finite")
    _, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError("decimal exponent must be finite")
    if len(digits) > MAX_DECIMAL_DIGITS:
        raise ValueError("decimal exceeds 28 significant digits")
    if max(0, -exponent) > MAX_DECIMAL_FRACTIONAL_DIGITS:
        raise ValueError("decimal exceeds 8 fractional digits")
    if not value.is_zero() and value.adjusted() + 1 > MAX_DECIMAL_DIGITS:
        raise ValueError("decimal exponent exceeds the bounded transport magnitude")
    return value


TransportDecimal = Annotated[Decimal, AfterValidator(validate_transport_decimal)]
PositiveTransportDecimal = Annotated[TransportDecimal, Field(gt=0)]
NonNegativeTransportDecimal = Annotated[TransportDecimal, Field(ge=0)]
