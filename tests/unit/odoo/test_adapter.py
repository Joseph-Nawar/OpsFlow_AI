"""Provider-free tests for the fixed Odoo JSON-2 transport."""

import asyncio
import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from opsflow.observability.runtime import Observability, reset_observability, set_observability
from opsflow.odoo import OdooERPAdapter, _bridge_result, _OdooFailure
from opsflow.order_sync.contracts import OrderSyncFailureCode, OrderSyncStepFailure
from opsflow.settings import Settings
from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
)


def _product(
    *,
    record_id: int = 30,
    sku: str = "SKU-001",
    uom_id: int | None = 40,
    currency_id: int = 10,
    list_price: float = 11.25,
    free_qty: float = 8.0,
) -> dict[str, object]:
    return {
        "id": record_id,
        "default_code": sku,
        "name": f"Trusted {sku}",
        "active": True,
        "sale_ok": True,
        "is_storable": True,
        "uom_id": [uom_id, "Units"] if uom_id is not None else False,
        "currency_id": [currency_id, "USD"],
        "product_tmpl_id": [record_id + 100, f"Template {sku}"],
        "lst_price": list_price,
        "free_qty": free_qty,
    }


def _lookup_handler(
    *,
    customer_rows: list[dict[str, object]] | None = None,
    product_rows: list[dict[str, object]] | None = None,
    requests: list[tuple[str, dict[str, object]]] | None = None,
):
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if requests is not None:
            requests.append((request.url.path, body))
        payloads: dict[str, object] = {
            "/json/2/res.company/read": [{"id": 1, "currency_id": [10, "USD"], "active": True}],
            "/json/2/stock.warehouse/read": [
                {"id": 2, "company_id": [1, "OpsFlow Demo"], "lot_stock_id": [9, "Stock"]}
            ],
            "/json/2/product.pricelist/read": [
                {"id": 3, "company_id": [1, "OpsFlow Demo"], "currency_id": [10, "USD"]}
            ],
            "/json/2/res.currency/read": [
                {"id": 10, "name": "USD", "active": True, "rounding": 0.01}
            ],
            "/json/2/product.pricelist.item/search_count": 0,
            "/json/2/res.partner/search_read": customer_rows
            if customer_rows is not None
            else [
                {
                    "id": 20,
                    "ref": "CUST-001",
                    "name": "Acme Industries",
                    "active": True,
                    "is_company": True,
                    "customer_rank": 1,
                    "company_id": False,
                }
            ],
            "/json/2/product.product/search_read": product_rows
            if product_rows is not None
            else [_product()],
        }
        payload = payloads.get(request.url.path)
        if payload is None:
            return httpx.Response(404, json={"error": "unexpected fake path"})
        return httpx.Response(200, json=payload)

    return respond


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        odoo_base_url="http://odoo.test",
        odoo_database="opsflow_test",
        odoo_api_key="test-api-key-sentinel",
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
    )


def test_json2_request_uses_database_header_and_bearer_key() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"id": 7}])

    adapter = OdooERPAdapter(_settings(), transport=httpx.MockTransport(respond))

    async def exercise() -> object:
        try:
            return await adapter._json2_call(
                "res.partner",
                "search_read",
                domain=[["ref", "=", "C-7"]],
                fields=["id", "ref"],
                limit=2,
            )
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == [{"id": 7}]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/json/2/res.partner/search_read"
    assert request.headers["authorization"] == "bearer test-api-key-sentinel"
    assert request.headers["x-odoo-database"] == "opsflow_test"
    assert request.read() == (b'{"domain":[["ref","=","C-7"]],"fields":["id","ref"],"limit":2}')


def test_transport_errors_map_to_bounded_failure_codes_without_body() -> None:
    sentinel = "odoo-private-traceback-and-response-sentinel"

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=sentinel)

    adapter = OdooERPAdapter(_settings(), transport=httpx.MockTransport(respond))

    async def exercise() -> None:
        try:
            await adapter._json2_call("res.partner", "search_read", domain=[], fields=["id"])
        finally:
            await adapter.aclose()

    with pytest.raises(_OdooFailure) as captured:
        asyncio.run(exercise())

    assert captured.value.code is OrderSyncFailureCode.PROVIDER_UNAVAILABLE
    assert sentinel not in str(captured.value)
    assert sentinel not in repr(captured.value)


def test_missing_json2_method_maps_to_configuration_without_body() -> None:
    sentinel = "missing-odoo-method-traceback-sentinel"

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text=sentinel)

    adapter = OdooERPAdapter(_settings(), transport=httpx.MockTransport(respond))

    async def exercise() -> None:
        try:
            await adapter._json2_call("sale.order", "unknown_method")
        finally:
            await adapter.aclose()

    with pytest.raises(_OdooFailure) as captured:
        asyncio.run(exercise())
    assert captured.value.code is OrderSyncFailureCode.INTEGRATION_CONFIG
    assert sentinel not in str(captured.value)


def test_bridge_result_accepts_only_bounded_confirmed_receipts() -> None:
    order_id = UUID("8c1f50e1-19dc-4a77-99b4-74764713b536")
    receipt = _bridge_result(
        {
            "outcome": "replayed",
            "opsflow_order_id": str(order_id),
            "sale_order_id": 17,
            "sale_order_name": "S00017",
            "confirmed_state": "sale",
        },
        order_id,
    )
    assert receipt.sale_order_id == 17
    assert receipt.sale_order_name == "S00017"

    for invalid in (
        {"outcome": "created", "sale_order_id": 17},
        {
            "outcome": "created",
            "opsflow_order_id": str(order_id),
            "sale_order_id": 17,
            "sale_order_name": "S00017",
            "confirmed_state": "draft",
        },
        {
            "outcome": "created",
            "opsflow_order_id": str(order_id),
            "sale_order_id": 17,
            "sale_order_name": "S00017",
            "confirmed_state": "sale",
            "debug": "must not be accepted",
        },
    ):
        failure = _bridge_result(invalid, order_id)
        assert isinstance(failure, OrderSyncStepFailure)
        assert failure.code is OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE


def test_bridge_concurrency_race_maps_to_existing_retryable_failure() -> None:
    order_id = UUID("8c1f50e1-19dc-4a77-99b4-74764713b536")

    result = _bridge_result({"outcome": "concurrency_retry"}, order_id)

    assert isinstance(result, OrderSyncStepFailure)
    assert result.code is OrderSyncFailureCode.PROVIDER_UNAVAILABLE


def test_lookup_maps_exact_partner_and_variant_fields() -> None:
    adapter = OdooERPAdapter(_settings(), transport=httpx.MockTransport(_lookup_handler()))
    request = BusinessDataLookupRequest("CUST-001", None, ("SKU-001",))

    async def exercise():
        try:
            return await adapter._lookup_snapshot(request)
        finally:
            await adapter.aclose()

    snapshot = asyncio.run(exercise())
    assert snapshot.trusted_data == TrustedBusinessData(
        customer_candidates=(TrustedCustomer("CUST-001", "Acme Industries", True),),
        products_by_line=(
            TrustedProduct(
                "SKU-001", "Trusted SKU-001", True, "USD", Decimal("11.25"), Decimal("8.0")
            ),
        ),
    )


def test_lookup_snapshot_preserves_provider_ids_and_uom_per_line() -> None:
    adapter = OdooERPAdapter(
        _settings(),
        transport=httpx.MockTransport(
            _lookup_handler(
                product_rows=[
                    _product(record_id=30, sku="SKU-B", uom_id=41),
                    _product(record_id=31, sku="SKU-A", uom_id=42),
                ]
            )
        ),
    )
    request = BusinessDataLookupRequest("CUST-001", None, ("SKU-A", "SKU-B"))

    async def exercise():
        try:
            return await adapter._lookup_snapshot(request)
        finally:
            await adapter.aclose()

    snapshot = asyncio.run(exercise())
    assert snapshot.customer_partner_ids == (20,)
    assert snapshot.product_ids_by_line == (31, 30)
    assert snapshot.uom_ids_by_line == (42, 41)
    assert snapshot.currency_ids_by_line == (10, 10)
    assert tuple(item.sku for item in snapshot.trusted_data.products_by_line if item) == (
        "SKU-A",
        "SKU-B",
    )


def test_lookup_uses_lst_price_and_free_qty_with_explicit_company_warehouse() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    adapter = OdooERPAdapter(
        _settings(),
        transport=httpx.MockTransport(_lookup_handler(requests=calls)),
    )

    async def exercise():
        try:
            return await adapter.get_validation_data(
                BusinessDataLookupRequest("CUST-001", None, ("SKU-001",))
            )
        finally:
            await adapter.aclose()

    data = asyncio.run(exercise())
    product = data.products_by_line[0]
    assert product is not None
    assert product.catalogue_price == Decimal("11.25")
    assert product.available_quantity == Decimal("8.0")
    product_call = next(
        body for path, body in calls if path.endswith("product.product/search_read")
    )
    assert product_call["fields"] == [
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
    ]
    assert product_call["context"] == {
        "allowed_company_ids": [1],
        "warehouse": 2,
        "active_test": False,
    }
    assert all("qty_available" not in body.get("fields", []) for _, body in calls)


def test_validation_lookup_observes_one_logical_odoo_operation() -> None:
    adapter = OdooERPAdapter(_settings(), transport=httpx.MockTransport(_lookup_handler()))
    observer = Observability({"odoo": "CONFIGURED"})
    token = set_observability(observer)

    async def exercise():
        try:
            return await adapter.get_validation_data(
                BusinessDataLookupRequest("CUST-001", None, ("SKU-001",))
            )
        finally:
            await adapter.aclose()

    try:
        data = asyncio.run(exercise())
    finally:
        reset_observability(token)

    assert data.products_by_line[0] is not None
    assert observer.integrations.snapshot()["odoo"]["observation"] == "HEALTHY"
    snapshot = observer.metrics.snapshot()
    assert sum(snapshot["counters"]["provider_calls_total"].values()) == 1
    assert (
        sum(item["count"] for item in snapshot["histograms"]["provider_duration_ms"].values()) == 1
    )


def test_validation_lookup_provider_failure_observes_bounded_odoo_failure() -> None:
    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="provider-private-response")

    adapter = OdooERPAdapter(_settings(), transport=httpx.MockTransport(unavailable))
    observer = Observability({"odoo": "CONFIGURED"})
    token = set_observability(observer)

    async def exercise():
        try:
            return await adapter.get_validation_data(
                BusinessDataLookupRequest("CUST-001", None, ("SKU-001",))
            )
        finally:
            await adapter.aclose()

    try:
        with pytest.raises(_OdooFailure) as captured:
            asyncio.run(exercise())
    finally:
        reset_observability(token)

    assert captured.value.code is OrderSyncFailureCode.PROVIDER_UNAVAILABLE
    assert observer.integrations.snapshot()["odoo"]["observation"] == "UNAVAILABLE"
    assert observer.integrations.snapshot()["odoo"]["failure_code"] == "PROVIDER_UNAVAILABLE"


def test_lookup_parses_negative_free_qty_without_treating_it_as_provider_error() -> None:
    adapter = OdooERPAdapter(
        _settings(),
        transport=httpx.MockTransport(_lookup_handler(product_rows=[_product(free_qty=-2.0)])),
    )
    request = BusinessDataLookupRequest("CUST-001", None, ("SKU-001",))

    async def exercise():
        try:
            return await adapter._lookup_snapshot(request)
        finally:
            await adapter.aclose()

    snapshot = asyncio.run(exercise())
    assert snapshot.trusted_data.products_by_line[0] is not None
    assert snapshot.trusted_data.products_by_line[0].available_quantity == Decimal("0")


def test_product_variant_effective_price_is_not_recomputed() -> None:
    # Odoo's variant lst_price is the trusted effective catalogue value; template
    # list_price and price_extra are deliberately not sent to OpsFlow.
    adapter = OdooERPAdapter(
        _settings(),
        transport=httpx.MockTransport(_lookup_handler(product_rows=[_product(list_price=12.75)])),
    )

    async def exercise():
        try:
            return await adapter.get_validation_data(
                BusinessDataLookupRequest("CUST-001", None, ("SKU-001",))
            )
        finally:
            await adapter.aclose()

    product = asyncio.run(exercise()).products_by_line[0]
    assert product is not None
    assert product.catalogue_price == Decimal("12.75")


def test_preflight_rejects_uom_mismatch_without_conversion() -> None:
    adapter = OdooERPAdapter(
        _settings(),
        transport=httpx.MockTransport(_lookup_handler(product_rows=[_product(uom_id=None)])),
    )

    async def exercise():
        try:
            return await adapter._lookup_snapshot(
                BusinessDataLookupRequest("CUST-001", None, ("SKU-001",))
            )
        finally:
            await adapter.aclose()

    with pytest.raises(_OdooFailure) as captured:
        asyncio.run(exercise())
    assert captured.value.code is OrderSyncFailureCode.TRUSTED_PRODUCT_CHANGED
