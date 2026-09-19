"""Deterministic synthetic external business-data provider for Phase 5 tests."""

from dataclasses import dataclass

from opsflow.validation.business_data import (
    TrustedBusinessDataContractError,
    normalize_customer_name,
)
from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
)


@dataclass(frozen=True, slots=True)
class SandboxBusinessDataProvider:
    """In-memory provider containing only synthetic customer/product records."""

    customers: tuple[TrustedCustomer, ...]
    products: tuple[TrustedProduct, ...]

    def __post_init__(self) -> None:
        if type(self.customers) is not tuple:
            raise TrustedBusinessDataContractError("sandbox customers must be a tuple")
        if type(self.products) is not tuple:
            raise TrustedBusinessDataContractError("sandbox products must be a tuple")
        if not all(type(customer) is TrustedCustomer for customer in self.customers):
            raise TrustedBusinessDataContractError("sandbox customers are invalid")
        if not all(type(product) is TrustedProduct for product in self.products):
            raise TrustedBusinessDataContractError("sandbox products are invalid")

        customer_references = [customer.reference for customer in self.customers]
        if len(set(customer_references)) != len(customer_references):
            raise TrustedBusinessDataContractError("sandbox customer references must be unique")
        product_skus = [product.sku for product in self.products]
        if len(set(product_skus)) != len(product_skus):
            raise TrustedBusinessDataContractError("sandbox SKUs must be unique")

        object.__setattr__(
            self,
            "customers",
            tuple(sorted(self.customers, key=lambda item: item.reference)),
        )
        object.__setattr__(
            self,
            "products",
            tuple(sorted(self.products, key=lambda item: item.sku)),
        )

    async def get_validation_data(
        self,
        request: BusinessDataLookupRequest,
    ) -> TrustedBusinessData:
        """Return deterministic exact customer and line-positioned SKU matches."""

        if not isinstance(request, BusinessDataLookupRequest):
            raise ValueError("business-data request has an invalid type")

        if request.customer_reference is not None:
            candidates = tuple(
                customer
                for customer in self.customers
                if customer.reference == request.customer_reference
            )
        elif request.customer_name is not None:
            normalized_name = normalize_customer_name(request.customer_name)
            candidates = tuple(
                customer
                for customer in self.customers
                if normalize_customer_name(customer.name) == normalized_name
            )
        else:
            candidates = ()

        products_by_line = tuple(
            next((product for product in self.products if product.sku == sku), None)
            for sku in request.skus
        )
        return TrustedBusinessData(candidates, products_by_line)
