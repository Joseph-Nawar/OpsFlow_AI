"""Bounded transport primitives for the Odoo 19 JSON-2 integration."""

from __future__ import annotations

import math
import time
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opsflow.application.errors import OrderNotFoundError
from opsflow.application.orders import get_order
from opsflow.domain import Order, OrderState, ValidationIssue
from opsflow.observability.runtime import current_observability, duration_ms
from opsflow.order_sync.contracts import (
    OdooOrderReceipt,
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepFailure,
    OrderSyncStepResult,
)
from opsflow.settings import Settings
from opsflow.validation.business_data import BusinessDataProvider
from opsflow.validation.engine import approved_order_trusted_data_issues
from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
)
from opsflow.validation.policy import ValidationPolicy

_ODOO_REQUEST_TIMEOUT_SECONDS = 20.0


class _OdooFailure(Exception):
    """An Odoo failure reduced to an existing bounded M9B category."""

    def __init__(self, code: OrderSyncFailureCode) -> None:
        self.code = code
        super().__init__(f"Odoo operation failed ({code.value}).")


@dataclass(frozen=True, slots=True)
class _OdooLookupSnapshot:
    """Trusted data plus private Odoo identities aligned to the public records."""

    trusted_data: TrustedBusinessData
    customer_partner_ids: tuple[int, ...]
    product_ids_by_line: tuple[int | None, ...]
    uom_ids_by_line: tuple[int | None, ...]
    currency_ids_by_line: tuple[int | None, ...]

    def __post_init__(self) -> None:
        if len(self.customer_partner_ids) != len(self.trusted_data.customer_candidates):
            raise ValueError("customer IDs must align with trusted candidates")
        line_count = len(self.trusted_data.products_by_line)
        if any(
            len(values) != line_count
            for values in (
                self.product_ids_by_line,
                self.uom_ids_by_line,
                self.currency_ids_by_line,
            )
        ):
            raise ValueError("Odoo product identities must align with trusted product lines")


class OdooERPAdapter(BusinessDataProvider):
    """One Odoo client boundary; provider operations are added on this class."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        policy: ValidationPolicy | None = None,
    ) -> None:
        required = (
            settings.odoo_base_url,
            settings.odoo_database,
            settings.odoo_api_key,
            settings.odoo_company_id,
            settings.odoo_warehouse_id,
            settings.odoo_pricelist_id,
        )
        if any(value is None for value in required):
            raise ValueError("complete Odoo settings are required")
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._policy = policy
        assert settings.odoo_base_url is not None
        assert settings.odoo_database is not None
        assert settings.odoo_api_key is not None
        self._client = httpx.AsyncClient(
            base_url=settings.odoo_base_url,
            headers={
                "Authorization": f"bearer {settings.odoo_api_key.get_secret_value()}",
                "X-Odoo-Database": settings.odoo_database,
            },
            timeout=httpx.Timeout(_ODOO_REQUEST_TIMEOUT_SECONDS),
            transport=transport,
        )

    async def aclose(self) -> None:
        """Release the persistent HTTPX connection pool."""

        await self._client.aclose()

    async def _json2_call(self, model: str, method: str, **arguments: object) -> object:
        """Call one fixed JSON-2 operation and discard unbounded error details."""

        try:
            response = await self._client.post(
                f"/json/2/{model}/{method}",
                json=arguments,
                timeout=httpx.Timeout(_ODOO_REQUEST_TIMEOUT_SECONDS),
            )
        except httpx.TransportError:
            raise _OdooFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE) from None

        if response.status_code in (401, 403):
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        if response.status_code == 404:
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        if response.status_code == 429 or response.status_code >= 500:
            raise _OdooFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        if not response.is_success:
            raise _OdooFailure(OrderSyncFailureCode.PROVIDER_REJECTED)
        try:
            return response.json()
        except (ValueError, UnicodeDecodeError):
            raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE) from None

    async def get_validation_data(
        self,
        request: BusinessDataLookupRequest,
    ) -> TrustedBusinessData:
        """Return Odoo-backed trusted records without provider IDs in the contract."""

        started_ns = time.perf_counter_ns()
        success = False
        failure_code: str | None = None
        try:
            result = (await self._lookup_snapshot(request)).trusted_data
            success = True
            failure_code = None
            return result
        except _OdooFailure as failure:
            failure_code = failure.code.value
            raise
        finally:
            observer = current_observability()
            if observer is not None and (success or failure_code is not None):
                with suppress(Exception):
                    observer.provider_completed(
                        provider="odoo",
                        operation=OrderSyncStep.ODOO_LOOKUP.value,
                        success=success,
                        duration_ms=duration_ms(started_ns),
                        failure_code=failure_code,
                    )

    async def execute(self, order_id: UUID, step: OrderSyncStep) -> OrderSyncStepResult:
        """Execute one Odoo checkpoint through the unchanged M9B executor seam."""

        if step not in (OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE):
            return OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        if self._sessionmaker is None or self._policy is None:
            return OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        try:
            order = await self._load_order_without_transaction(order_id)
        except OrderNotFoundError:
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        if order.state not in (OrderState.APPROVED, OrderState.SYNCING):
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_REJECTED)

        if order.customer_reference is None:
            return OrderSyncStepFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING)
        request = BusinessDataLookupRequest(
            customer_reference=order.customer_reference,
            customer_name=None,
            skus=tuple(line.sku for line in order.lines),
        )
        if step is OrderSyncStep.ODOO_LOOKUP:
            try:
                snapshot = await self._lookup_snapshot(request)
            except _OdooFailure as failure:
                return OrderSyncStepFailure(failure.code)
            issues = approved_order_trusted_data_issues(order, snapshot.trusted_data, self._policy)
            failure_code = _preflight_failure_code(issues)
            if failure_code is not None:
                return OrderSyncStepFailure(failure_code)
            return None

        try:
            existing_identity = await self._bridge_identity_exists(order_id)
            snapshot = await self._lookup_snapshot(request)
        except _OdooFailure as failure:
            return OrderSyncStepFailure(failure.code)

        # A previous bridge request may have committed before OpsFlow persisted
        # its receipt. Let the atomic bridge reconcile that identity before
        # current stock/catalogue eligibility can block the replay. For a new
        # external order, repeat Python's policy preflight against this fresh
        # snapshot before allowing the bridge to write.
        if not existing_identity:
            issues = approved_order_trusted_data_issues(order, snapshot.trusted_data, self._policy)
            failure_code = _preflight_failure_code(issues)
            if failure_code is not None:
                return OrderSyncStepFailure(failure_code)

        try:
            arguments = _bridge_arguments(order, snapshot, self._settings)
        except _OdooFailure as failure:
            return OrderSyncStepFailure(failure.code)
        try:
            result = await self._json2_call(
                "sale.order",
                "opsflow_create_or_get_sale_order",
                **arguments,
            )
        except _OdooFailure as failure:
            return OrderSyncStepFailure(failure.code)
        return _bridge_result(result, order_id)

    async def _bridge_identity_exists(self, order_id: UUID) -> bool:
        """Read only enough to preserve replay before current-data preflight."""

        company_id = self._settings.odoo_company_id
        if company_id is None:
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        value = await self._json2_call(
            "sale.order",
            "search_read",
            domain=[["opsflow_order_id", "=", str(order_id)]],
            fields=["id", "opsflow_order_id"],
            limit=2,
            context={"allowed_company_ids": [company_id], "active_test": False},
        )
        records = _records(value)
        if len(records) > 1:
            raise _OdooFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        if not records:
            return False
        if records[0].get("opsflow_order_id") != str(order_id):
            raise _OdooFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        _record_id(records[0])
        return True

    async def _load_order_without_transaction(self, order_id: UUID) -> Order:
        """Read the approved snapshot in a short session closed before provider I/O."""

        assert self._sessionmaker is not None
        async with self._sessionmaker() as session:
            try:
                persisted = await get_order(session, order_id)
                return persisted.order
            finally:
                await session.rollback()

    async def _lookup_snapshot(
        self,
        request: BusinessDataLookupRequest,
    ) -> _OdooLookupSnapshot:
        """Resolve exact customer/SKU identities and scoped trusted Odoo values."""

        currency_id, currency_code = await self._read_configured_setup()
        company_id = cast(int, self._settings.odoo_company_id)
        warehouse_id = cast(int, self._settings.odoo_warehouse_id)
        customer_candidates: tuple[TrustedCustomer, ...] = ()
        customer_ids: tuple[int, ...] = ()
        if request.customer_reference is not None:
            customer_payload = await self._json2_call(
                "res.partner",
                "search_read",
                domain=[["ref", "=", request.customer_reference]],
                fields=["id", "ref", "name", "active", "is_company", "customer_rank", "company_id"],
                limit=2,
                context={"allowed_company_ids": [company_id], "active_test": False},
            )
            customer_records = _records(customer_payload)
            if len(customer_records) > 1:
                raise _OdooFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_AMBIGUOUS)
            if customer_records:
                record = customer_records[0]
                partner_id = _record_id(record)
                reference = _required_string(record, "ref")
                name = _required_string(record, "name")
                active = _required_bool(record, "active")
                is_company = _required_bool(record, "is_company")
                customer_rank = _required_nonnegative_int(record, "customer_rank")
                company_value = _relation_id(record.get("company_id"))
                if reference != request.customer_reference:
                    raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
                eligible = (
                    active
                    and is_company
                    and customer_rank > 0
                    and company_value
                    in (
                        None,
                        company_id,
                    )
                )
                customer_candidates = (TrustedCustomer(reference, name, eligible),)
                customer_ids = (partner_id,)

        requested_skus = tuple(dict.fromkeys(sku for sku in request.skus if sku is not None))
        records_by_sku: dict[str, dict[str, object]] = {}
        if requested_skus:
            product_payload = await self._json2_call(
                "product.product",
                "search_read",
                domain=[["default_code", "in", list(requested_skus)]],
                fields=[
                    "id",
                    "default_code",
                    "name",
                    "active",
                    "sale_ok",
                    "is_storable",
                    "uom_id",
                    "currency_id",
                    "product_tmpl_id",
                    "lst_price",
                    "free_qty",
                ],
                limit=201,
                context={
                    "allowed_company_ids": [company_id],
                    "warehouse": warehouse_id,
                    "active_test": False,
                },
            )
            product_records = _records(product_payload)
            if len(product_records) > 201:
                raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
            for record in product_records:
                sku = _required_string(record, "default_code")
                if sku not in requested_skus:
                    raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
                if sku in records_by_sku:
                    raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED)
                records_by_sku[sku] = record

        products: list[TrustedProduct | None] = []
        product_ids: list[int | None] = []
        uom_ids: list[int | None] = []
        currency_ids: list[int | None] = []
        for requested_sku in request.skus:
            if requested_sku is None or requested_sku not in records_by_sku:
                products.append(None)
                product_ids.append(None)
                uom_ids.append(None)
                currency_ids.append(None)
                continue
            record = records_by_sku[requested_sku]
            product_id = _record_id(record)
            uom_id = _relation_id(record.get("uom_id"))
            actual_currency_id = _relation_id(record.get("currency_id"))
            _relation_id(record.get("product_tmpl_id"))
            if uom_id is None or actual_currency_id is None:
                raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED)
            if actual_currency_id != currency_id:
                raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED)
            active = _required_bool(record, "active")
            sale_ok = _required_bool(record, "sale_ok")
            is_storable = _required_bool(record, "is_storable")
            catalogue_price = _required_decimal(record, "lst_price")
            # Odoo can report negative free stock. The shared trusted-data
            # contract is nonnegative, so retain its create-time meaning as
            # zero available while allowing existing-identity reconciliation
            # to continue to the atomic bridge.
            free_quantity = _required_decimal(record, "free_qty", allow_negative=True)
            available_quantity = max(free_quantity, Decimal("0"))
            products.append(
                TrustedProduct(
                    sku=_required_string(record, "default_code"),
                    description=_required_string(record, "name"),
                    active=active and sale_ok and is_storable,
                    currency=currency_code,
                    catalogue_price=catalogue_price,
                    available_quantity=available_quantity,
                )
            )
            product_ids.append(product_id)
            uom_ids.append(uom_id)
            currency_ids.append(actual_currency_id)

        return _OdooLookupSnapshot(
            trusted_data=TrustedBusinessData(customer_candidates, tuple(products)),
            customer_partner_ids=customer_ids,
            product_ids_by_line=tuple(product_ids),
            uom_ids_by_line=tuple(uom_ids),
            currency_ids_by_line=tuple(currency_ids),
        )

    async def _read_configured_setup(self) -> tuple[int, str]:
        """Check the fixed company, warehouse, pricelist and currency setup."""

        company_id = cast(int, self._settings.odoo_company_id)
        warehouse_id = cast(int, self._settings.odoo_warehouse_id)
        pricelist_id = cast(int, self._settings.odoo_pricelist_id)
        context = {"allowed_company_ids": [company_id]}
        company = _single_record(
            await self._json2_call(
                "res.company",
                "read",
                ids=[company_id],
                fields=["id", "currency_id", "active"],
                context=context,
            ),
            OrderSyncFailureCode.INTEGRATION_CONFIG,
        )
        if _record_id(company) != company_id or not _required_bool(company, "active"):
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        currency_id = _relation_id(company.get("currency_id"))
        if currency_id is None:
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)

        warehouse = _single_record(
            await self._json2_call(
                "stock.warehouse",
                "read",
                ids=[warehouse_id],
                fields=["id", "company_id", "lot_stock_id"],
                context=context,
            ),
            OrderSyncFailureCode.INTEGRATION_CONFIG,
        )
        if (
            _record_id(warehouse) != warehouse_id
            or _relation_id(warehouse.get("company_id")) != company_id
            or _relation_id(warehouse.get("lot_stock_id")) is None
        ):
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)

        pricelist = _single_record(
            await self._json2_call(
                "product.pricelist",
                "read",
                ids=[pricelist_id],
                fields=["id", "company_id", "currency_id"],
                context=context,
            ),
            OrderSyncFailureCode.INTEGRATION_CONFIG,
        )
        pricelist_company_id = _relation_id(pricelist.get("company_id"))
        if (
            _record_id(pricelist) != pricelist_id
            or pricelist_company_id not in (None, company_id)
            or _relation_id(pricelist.get("currency_id")) != currency_id
        ):
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)

        currency = _single_record(
            await self._json2_call(
                "res.currency",
                "read",
                ids=[currency_id],
                fields=["id", "name", "active", "rounding"],
                context=context,
            ),
            OrderSyncFailureCode.INTEGRATION_CONFIG,
        )
        currency_code = _required_string(currency, "name")
        if (
            _record_id(currency) != currency_id
            or not _required_bool(currency, "active")
            or len(currency_code) != 3
            or not currency_code.isascii()
            or not currency_code.isalpha()
            or currency_code.upper() != currency_code
            or _required_decimal(currency, "rounding") <= 0
        ):
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)

        rule_count = await self._json2_call(
            "product.pricelist.item",
            "search_count",
            domain=[["pricelist_id", "=", pricelist_id]],
            context=context,
        )
        if type(rule_count) is not int or rule_count != 0:
            raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        return currency_id, currency_code


def _records(value: object) -> tuple[dict[str, object], ...]:
    if type(value) is not list or not all(type(record) is dict for record in value):
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return tuple(cast(dict[str, object], record) for record in value)


def _single_record(value: object, code: OrderSyncFailureCode) -> dict[str, object]:
    records = _records(value)
    if len(records) != 1:
        raise _OdooFailure(code)
    return records[0]


def _record_id(record: dict[str, object]) -> int:
    value = record.get("id")
    if type(value) is not int or value <= 0:
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return value


def _required_string(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if type(value) is not str or not value.strip():
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return value


def _required_bool(record: dict[str, object], field: str) -> bool:
    value = record.get(field)
    if type(value) is not bool:
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return value


def _required_nonnegative_int(record: dict[str, object], field: str) -> int:
    value = record.get(field)
    if type(value) is not int or value < 0:
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return value


def _relation_id(value: object) -> int | None:
    if value is None or value is False:
        return None
    if type(value) is int and value > 0:
        return value
    if (
        type(value) is list
        and len(value) == 2
        and type(value[0]) is int
        and value[0] > 0
        and type(value[1]) is str
    ):
        return value[0]
    raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)


def _required_decimal(
    record: dict[str, object], field: str, *, allow_negative: bool = False
) -> Decimal:
    value = record.get(field)
    if type(value) not in (int, float, str) or type(value) is bool:
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    if type(value) is float and not math.isfinite(value):
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE) from None
    if not result.is_finite() or (result < 0 and not allow_negative):
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return result


def _preflight_failure_code(
    issues: tuple[ValidationIssue, ...],
) -> OrderSyncFailureCode | None:
    """Reduce the existing deterministic trusted-data issues to bounded sync codes."""

    rules = {
        "CUSTOMER_REQUIRED": OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING,
        "UNKNOWN_CUSTOMER": OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING,
        "INACTIVE_CUSTOMER": OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING,
        "AMBIGUOUS_CUSTOMER": OrderSyncFailureCode.TRUSTED_CUSTOMER_AMBIGUOUS,
        "SKU_REQUIRED": OrderSyncFailureCode.TRUSTED_PRODUCT_MISSING,
        "UNKNOWN_SKU": OrderSyncFailureCode.TRUSTED_PRODUCT_MISSING,
        "INACTIVE_SKU": OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED,
        "INVENTORY_UNAVAILABLE": OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE,
        "INSUFFICIENT_INVENTORY": OrderSyncFailureCode.INVENTORY_INSUFFICIENT,
        "CURRENCY_REQUIRED": OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED,
        "UNSUPPORTED_CURRENCY": OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED,
        "PRODUCT_CURRENCY_MISMATCH": OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED,
        "CATALOGUE_PRICE_UNAVAILABLE": OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED,
        "PRICE_OUTSIDE_TOLERANCE": OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED,
    }
    for issue in issues:
        code = rules.get(issue.rule_code)
        if code is None:
            return OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE
        return code
    return None


def _bridge_arguments(
    order: Order,
    snapshot: _OdooLookupSnapshot,
    settings: Settings,
) -> dict[str, object]:
    """Build only the fixed, named bridge arguments from the approved snapshot."""

    company_id = settings.odoo_company_id
    warehouse_id = settings.odoo_warehouse_id
    pricelist_id = settings.odoo_pricelist_id
    if company_id is None or warehouse_id is None or pricelist_id is None:
        raise _OdooFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
    if order.customer_reference is None or order.po_number is None:
        raise _OdooFailure(OrderSyncFailureCode.PROVIDER_REJECTED)
    if len(snapshot.customer_partner_ids) != 1 or not order.lines:
        raise _OdooFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING)
    customer = snapshot.trusted_data.customer_candidates
    if len(customer) != 1 or customer[0].reference != order.customer_reference:
        raise _OdooFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING)
    currency_ids = snapshot.currency_ids_by_line
    first_product = snapshot.trusted_data.products_by_line[0]
    if (
        not currency_ids
        or currency_ids[0] is None
        or any(currency_id != currency_ids[0] for currency_id in currency_ids)
        or first_product is None
        or order.currency != first_product.currency
    ):
        raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED)

    lines: list[dict[str, object]] = []
    for index, order_line in enumerate(order.lines):
        trusted = snapshot.trusted_data.products_by_line[index]
        product_id = snapshot.product_ids_by_line[index]
        uom_id = snapshot.uom_ids_by_line[index]
        if trusted is None or product_id is None:
            raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_MISSING)
        if order_line.sku is None or trusted.sku != order_line.sku:
            raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED)
        if uom_id is None:
            raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED)
        if order_line.submitted_price is None or trusted.catalogue_price is None:
            raise _OdooFailure(OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED)
        line: dict[str, object] = {
            "sequence": index + 1,
            "product_id": product_id,
            "sku": order_line.sku,
            "uom_id": uom_id,
            "quantity": _decimal_text(order_line.quantity),
            "submitted_price": _decimal_text(order_line.submitted_price),
            "expected_lst_price": _decimal_text(trusted.catalogue_price),
        }
        if order_line.description is not None:
            line["description"] = order_line.description
        lines.append(line)

    return {
        "opsflow_order_id": str(order.id),
        "company_id": company_id,
        "warehouse_id": warehouse_id,
        "pricelist_id": pricelist_id,
        "currency_id": currency_ids[0],
        "partner_id": snapshot.customer_partner_ids[0],
        "customer_reference": order.customer_reference,
        "client_order_ref": order.po_number,
        "requested_delivery_date": (
            order.requested_delivery_date.isoformat()
            if order.requested_delivery_date is not None
            else None
        ),
        "lines": lines,
    }


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _bridge_result(value: object, order_id: UUID) -> OrderSyncStepResult:
    """Validate the exact bounded bridge envelope before returning a receipt."""

    if type(value) is not dict:
        return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    outcome = value.get("outcome")
    if outcome == "conflict" and value == {
        "outcome": "conflict",
        "failure_code": OrderSyncFailureCode.IDEMPOTENCY_CONFLICT.value,
    }:
        return OrderSyncStepFailure(OrderSyncFailureCode.IDEMPOTENCY_CONFLICT)
    if outcome == "reconciliation_required" and value == {
        "outcome": "reconciliation_required",
        "failure_code": OrderSyncFailureCode.RECONCILIATION_REQUIRED.value,
    }:
        return OrderSyncStepFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
    if value == {"outcome": "concurrency_retry"}:
        return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
    if outcome == "rejected":
        if set(value) != {"outcome", "failure_code"}:
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        failure_code = value.get("failure_code")
        if type(failure_code) is not str:
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        try:
            code = OrderSyncFailureCode(failure_code)
        except ValueError:
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        allowed = {
            OrderSyncFailureCode.INTEGRATION_CONFIG,
            OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING,
            OrderSyncFailureCode.TRUSTED_CUSTOMER_AMBIGUOUS,
            OrderSyncFailureCode.TRUSTED_PRODUCT_MISSING,
            OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED,
            OrderSyncFailureCode.INVENTORY_INSUFFICIENT,
            OrderSyncFailureCode.PROVIDER_REJECTED,
        }
        return (
            OrderSyncStepFailure(code)
            if code in allowed
            else OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        )

    if outcome not in ("created", "replayed") or set(value) != {
        "outcome",
        "opsflow_order_id",
        "sale_order_id",
        "sale_order_name",
        "confirmed_state",
    }:
        return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    if (
        value.get("opsflow_order_id") != str(order_id)
        or type(value.get("sale_order_id")) is not int
        or value["sale_order_id"] <= 0
        or type(value.get("sale_order_name")) is not str
        or not value["sale_order_name"].strip()
        or len(value["sale_order_name"]) > 256
        or value.get("confirmed_state") != "sale"
    ):
        return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return OdooOrderReceipt(value["sale_order_id"], value["sale_order_name"])
