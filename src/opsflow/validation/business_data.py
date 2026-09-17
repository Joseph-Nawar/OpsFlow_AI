"""External trusted business-data contracts for deterministic validation."""

from typing import Protocol

from opsflow.extraction.models import ExtractionDraft
from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
)


class TrustedBusinessDataContractError(ValueError):
    """Raised when a provider returns invalid trusted reference data."""


def normalize_customer_name(value: str) -> str:
    """Normalize a customer name using the locked exact-match procedure."""

    if not isinstance(value, str):
        raise ValueError("customer name must be a string")
    return " ".join(value.casefold().split())


class BusinessDataProvider(Protocol):
    """Async provider contract for external customer/product reference data."""

    async def get_validation_data(
        self,
        request: BusinessDataLookupRequest,
    ) -> TrustedBusinessData:
        """Return exact trusted reference matches for one draft lookup."""


def validate_trusted_business_data(
    draft: ExtractionDraft,
    data: TrustedBusinessData,
) -> None:
    """Validate the structural and ordering contract of provider result data."""

    if not isinstance(draft, ExtractionDraft):
        raise TrustedBusinessDataContractError("provider result was paired with an invalid draft")
    if not isinstance(data, TrustedBusinessData):
        raise TrustedBusinessDataContractError("provider returned invalid trusted business data")
    if len(data.products_by_line) != len(draft.lines):
        raise TrustedBusinessDataContractError(
            "provider product results must match the draft line count"
        )

    references: list[str] = []
    for candidate in data.customer_candidates:
        if type(candidate) is not TrustedCustomer:
            raise TrustedBusinessDataContractError("provider returned an invalid customer record")
        if candidate.reference in references:
            raise TrustedBusinessDataContractError(
                "provider returned duplicate customer references"
            )
        references.append(candidate.reference)
    if tuple(references) != tuple(sorted(references)):
        raise TrustedBusinessDataContractError(
            "provider customer candidates are not in canonical reference order"
        )

    for product in data.products_by_line:
        if product is not None and type(product) is not TrustedProduct:
            raise TrustedBusinessDataContractError("provider returned an invalid product record")
