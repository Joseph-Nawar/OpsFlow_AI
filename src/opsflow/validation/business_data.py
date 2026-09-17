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

    if draft.customer_reference is not None:
        if any(
            candidate.reference != draft.customer_reference
            for candidate in data.customer_candidates
        ):
            raise TrustedBusinessDataContractError(
                "provider customer references do not match the requested reference"
            )
    elif draft.customer_name is not None:
        normalized_name = normalize_customer_name(draft.customer_name)
        if any(
            normalize_customer_name(candidate.name) != normalized_name
            for candidate in data.customer_candidates
        ):
            raise TrustedBusinessDataContractError(
                "provider customer candidate names do not match the requested normalized name"
            )
    elif data.customer_candidates:
        raise TrustedBusinessDataContractError(
            "provider returned customer candidates without a requested identity"
        )

    for product in data.products_by_line:
        if product is not None and type(product) is not TrustedProduct:
            raise TrustedBusinessDataContractError("provider returned an invalid product record")

    for line, product in zip(draft.lines, data.products_by_line, strict=True):
        if line.sku is None and product is not None:
            raise TrustedBusinessDataContractError(
                "provider returned a product for a line without an SKU"
            )
        if line.sku is not None and product is not None and product.sku != line.sku:
            raise TrustedBusinessDataContractError(
                "provider product does not match the requested line SKU"
            )
