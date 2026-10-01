"""Explicit opt-in JSON-2 checks for a disposable Odoo 19 Community database."""

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from opsflow.settings import Settings

_ROLLBACK_PROBE_ORDER_ID = "00000000-0000-4000-8000-000000000009"
_NONCONFIRMING_PROBE_ORDER_ID = "00000000-0000-4000-8000-000000000010"


def _live_settings() -> tuple[Settings, str, str]:
    if os.environ.get("OPSFLOW_ODOO_LIVE_TESTS") != "1":
        pytest.skip("set OPSFLOW_ODOO_LIVE_TESTS=1 for the disposable Odoo database")
    settings = Settings(_env_file=None)
    required = (
        settings.odoo_base_url,
        settings.odoo_database,
        settings.odoo_api_key,
        settings.odoo_company_id,
        settings.odoo_warehouse_id,
        settings.odoo_pricelist_id,
    )
    if any(value is None for value in required):
        pytest.fail("complete disposable Odoo runtime settings are required")
    customer_ref = os.environ.get("OPSFLOW_ODOO_M9C_TEST_CUSTOMER_REFERENCE")
    sku = os.environ.get("OPSFLOW_ODOO_M9C_TEST_SKU")
    if not customer_ref or not sku:
        pytest.fail("synthetic Odoo customer reference and SKU are required")
    return settings, customer_ref, sku


def _client(settings: Settings) -> httpx.AsyncClient:
    assert settings.odoo_base_url is not None
    assert settings.odoo_database is not None
    assert settings.odoo_api_key is not None
    return httpx.AsyncClient(
        base_url=settings.odoo_base_url,
        headers={
            "Authorization": f"bearer {settings.odoo_api_key.get_secret_value()}",
            "X-Odoo-Database": settings.odoo_database,
        },
        timeout=httpx.Timeout(20),
    )


def _unauthorized_client(settings: Settings) -> httpx.AsyncClient:
    api_key = os.environ.get("OPSFLOW_ODOO_M9C_UNAUTHORIZED_API_KEY")
    if not api_key:
        pytest.fail("test-only ordinary-user Odoo API key is required")
    assert settings.odoo_base_url is not None
    assert settings.odoo_database is not None
    return httpx.AsyncClient(
        base_url=settings.odoo_base_url,
        headers={
            "Authorization": f"bearer {api_key}",
            "X-Odoo-Database": settings.odoo_database,
        },
        timeout=httpx.Timeout(20),
    )


async def _call(client: httpx.AsyncClient, model: str, method: str, **arguments: object) -> object:
    response = await client.post(f"/json/2/{model}/{method}", json=arguments)
    if not response.is_success:
        raise AssertionError(f"disposable Odoo {model}.{method} request failed")
    return response.json()


async def _make_payload(
    client: httpx.AsyncClient,
    settings: Settings,
    customer_ref: str,
    sku: str,
    order_id: str,
) -> dict[str, object]:
    assert settings.odoo_company_id is not None
    assert settings.odoo_warehouse_id is not None
    assert settings.odoo_pricelist_id is not None
    company_id = settings.odoo_company_id
    warehouse_id = settings.odoo_warehouse_id
    pricelist_id = settings.odoo_pricelist_id
    context = {"allowed_company_ids": [company_id], "active_test": False}
    company = await _call(
        client,
        "res.company",
        "read",
        ids=[company_id],
        fields=["id", "currency_id", "active"],
        context=context,
    )
    warehouse = await _call(
        client,
        "stock.warehouse",
        "read",
        ids=[warehouse_id],
        fields=["id", "company_id", "lot_stock_id"],
        context=context,
    )
    pricelist = await _call(
        client,
        "product.pricelist",
        "read",
        ids=[pricelist_id],
        fields=["id", "company_id", "currency_id"],
        context=context,
    )
    if (
        not isinstance(company, list)
        or len(company) != 1
        or not company[0].get("active")
        or not isinstance(warehouse, list)
        or len(warehouse) != 1
        or warehouse[0].get("company_id", [None])[0] != company_id
        or not isinstance(pricelist, list)
        or len(pricelist) != 1
    ):
        raise AssertionError("disposable Odoo company/warehouse/pricelist setup is invalid")
    currency_id = company[0]["currency_id"][0]
    if pricelist[0].get("currency_id", [None])[0] != currency_id:
        raise AssertionError("disposable Odoo pricelist currency does not match the company")
    rules = await _call(
        client,
        "product.pricelist.item",
        "search_count",
        domain=[["pricelist_id", "=", pricelist_id]],
        context=context,
    )
    if rules != 0:
        raise AssertionError("disposable Odoo pricelist must be rule-free")

    partners = await _call(
        client,
        "res.partner",
        "search_read",
        domain=[["ref", "=", customer_ref]],
        fields=["id", "ref", "active", "is_company", "customer_rank", "company_id"],
        limit=2,
        context=context,
    )
    products = await _call(
        client,
        "product.product",
        "search_read",
        domain=[["default_code", "=", sku]],
        fields=[
            "id",
            "default_code",
            "active",
            "sale_ok",
            "is_storable",
            "currency_id",
            "uom_id",
            "lst_price",
            "free_qty",
        ],
        limit=2,
        context={**context, "warehouse": warehouse_id},
    )
    if (
        not isinstance(partners, list)
        or len(partners) != 1
        or not isinstance(products, list)
        or len(products) != 1
    ):
        raise AssertionError("disposable Odoo synthetic customer/SKU must resolve uniquely")
    partner = partners[0]
    product = products[0]
    if (
        partner.get("ref") != customer_ref
        or not partner.get("active")
        or not partner.get("is_company")
        or partner.get("customer_rank", 0) <= 0
        or product.get("default_code") != sku
        or not product.get("active")
        or not product.get("sale_ok")
        or not product.get("is_storable")
        or product.get("currency_id", [None])[0] != currency_id
        or product.get("free_qty", 0) < 1
    ):
        raise AssertionError("disposable Odoo synthetic customer/product is not eligible")
    price = format(Decimal(str(product["lst_price"])), "f")
    return {
        "opsflow_order_id": order_id,
        "company_id": company_id,
        "warehouse_id": warehouse_id,
        "pricelist_id": pricelist_id,
        "currency_id": currency_id,
        "partner_id": partner["id"],
        "customer_reference": customer_ref,
        "client_order_ref": f"M9C disposable probe {order_id[:8]}",
        "requested_delivery_date": None,
        "lines": [
            {
                "sequence": 1,
                "product_id": product["id"],
                "sku": sku,
                "uom_id": product["uom_id"][0],
                "quantity": "1",
                "submitted_price": price,
                "expected_lst_price": price,
                "description": "Synthetic M9C disposable integration probe",
            }
        ],
    }


async def _read_order(client: httpx.AsyncClient, order_id: str) -> list[dict[str, object]]:
    value = await _call(
        client,
        "sale.order",
        "search_read",
        domain=[["opsflow_order_id", "=", order_id]],
        fields=["id", "name", "state", "opsflow_order_id"],
        limit=2,
        context={"active_test": False},
    )
    assert isinstance(value, list)
    return value


def test_json2_lost_local_receipt_replay_returns_one_order() -> None:
    settings, customer_ref, sku = _live_settings()

    async def exercise() -> None:
        async with _client(settings) as client:
            order_id = str(uuid4())
            payload = await _make_payload(client, settings, customer_ref, sku, order_id)
            first_response = await client.post(
                "/json/2/sale.order/opsflow_create_or_get_sale_order", json=payload
            )
            assert first_response.is_success, "first disposable bridge request must succeed"
            del first_response  # Simulate a committed provider call with no local receipt.

            independent_first_read = await _read_order(client, order_id)
            assert len(independent_first_read) == 1
            assert independent_first_read[0]["state"] == "sale"

            replay = await _call(
                client,
                "sale.order",
                "opsflow_create_or_get_sale_order",
                **payload,
            )
            assert isinstance(replay, dict)
            assert replay.get("outcome") == "replayed"
            assert replay.get("sale_order_id") == independent_first_read[0]["id"]
            assert replay.get("sale_order_name") == independent_first_read[0]["name"]

            independent_final_read = await _read_order(client, order_id)
            count = await _call(
                client,
                "sale.order",
                "search_count",
                domain=[["opsflow_order_id", "=", order_id]],
                context={"active_test": False},
            )
            assert len(independent_final_read) == 1
            assert count == 1

    asyncio.run(exercise())


def test_json2_concurrent_same_uuid_converges_to_one_order() -> None:
    settings, customer_ref, sku = _live_settings()

    async def exercise() -> None:
        order_id = str(uuid4())
        async with _client(settings) as first, _client(settings) as second:
            payload = await _make_payload(first, settings, customer_ref, sku, order_id)
            payload["client_order_ref"] = f"M9C-TEST-RACE:{order_id}"
            first_result, second_result = await asyncio.gather(
                _call(first, "sale.order", "opsflow_create_or_get_sale_order", **payload),
                _call(second, "sale.order", "opsflow_create_or_get_sale_order", **payload),
            )
            outcomes = (first_result, second_result)
            assert all(isinstance(result, dict) for result in outcomes)
            receipt = next(
                result
                for result in outcomes
                if isinstance(result, dict) and result.get("outcome") == "created"
            )
            loser = next(result for result in outcomes if result is not receipt)
            assert loser == {"outcome": "concurrency_retry"}
            rows = await _read_order(first, order_id)
            assert len(rows) == 1
            assert rows[0]["state"] == "sale"
            replay = await _call(
                second,
                "sale.order",
                "opsflow_create_or_get_sale_order",
                **payload,
            )
            assert replay["outcome"] == "replayed"
            assert replay["sale_order_id"] == receipt["sale_order_id"]
            assert replay["sale_order_name"] == receipt["sale_order_name"]
            assert (
                await _call(
                    first,
                    "sale.order",
                    "search_count",
                    domain=[["opsflow_order_id", "=", order_id]],
                    context={"active_test": False},
                )
                == 1
            )

    asyncio.run(exercise())


def test_json2_confirmation_failure_rolls_back_request_transaction() -> None:
    settings, customer_ref, sku = _live_settings()

    async def exercise() -> None:
        async with _client(settings) as client:
            payload = await _make_payload(
                client,
                settings,
                customer_ref,
                sku,
                _ROLLBACK_PROBE_ORDER_ID,
            )
            response = await client.post(
                "/json/2/sale.order/opsflow_create_or_get_sale_order", json=payload
            )
            assert not response.is_success, "failure probe must reject confirmation"
            del response
            rows = await _read_order(client, _ROLLBACK_PROBE_ORDER_ID)
            assert rows == []
            count = await _call(
                client,
                "sale.order",
                "search_count",
                domain=[["opsflow_order_id", "=", _ROLLBACK_PROBE_ORDER_ID]],
                context={"active_test": False},
            )
            assert count == 0

    asyncio.run(exercise())


def test_json2_nonconfirming_success_rolls_back_request_transaction() -> None:
    settings, customer_ref, sku = _live_settings()

    async def exercise() -> None:
        async with _client(settings) as client:
            payload = await _make_payload(
                client,
                settings,
                customer_ref,
                sku,
                _NONCONFIRMING_PROBE_ORDER_ID,
            )
            response = await client.post(
                "/json/2/sale.order/opsflow_create_or_get_sale_order", json=payload
            )
            assert not response.is_success, "nonconfirming probe must abort the request"
            del response
            rows = await _read_order(client, _NONCONFIRMING_PROBE_ORDER_ID)
            assert rows == []
            count = await _call(
                client,
                "sale.order",
                "search_count",
                domain=[["opsflow_order_id", "=", _NONCONFIRMING_PROBE_ORDER_ID]],
                context={"active_test": False},
            )
            assert count == 0

    asyncio.run(exercise())


def test_json2_bridge_rejects_ordinary_sales_user_without_bridge_group() -> None:
    settings, customer_ref, sku = _live_settings()

    async def exercise() -> None:
        order_id = str(uuid4())
        async with _client(settings) as authorized, _unauthorized_client(settings) as unauthorized:
            payload = await _make_payload(authorized, settings, customer_ref, sku, order_id)
            response = await unauthorized.post(
                "/json/2/sale.order/opsflow_create_or_get_sale_order",
                json=payload,
            )
            assert response.is_success, "bridge denial is a bounded method outcome"
            assert response.json() == {
                "outcome": "rejected",
                "failure_code": "INTEGRATION_CONFIG",
            }
            assert await _read_order(authorized, order_id) == []
            count = await _call(
                authorized,
                "sale.order",
                "search_count",
                domain=[["opsflow_order_id", "=", order_id]],
                context={"active_test": False},
            )
            assert count == 0

    asyncio.run(exercise())
