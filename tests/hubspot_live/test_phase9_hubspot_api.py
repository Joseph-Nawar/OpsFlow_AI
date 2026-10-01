"""Opt-in HubSpot 2026-09 synthetic account and M9B recovery proof."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from opsflow.application.order_sync import execute_next_order_sync
from opsflow.domain import OrderState
from opsflow.hubspot import HUBSPOT_API_BASE_URL, HubSpotCRMAdapter
from opsflow.order_sync.contracts import (
    ExecuteNextKind,
    OdooOrderReceipt,
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepFailure,
)
from opsflow.order_sync.executor import Phase9OrderSyncExecutor
from opsflow.persistence.models import OrderLineModel, OrderModel, OrderSyncModel
from opsflow.settings import Settings
from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
)

_ROOT = Path(__file__).parents[2]
_PORTAL_ID = 149461984
_COMPANY_IDENTITY = "opsflow_customer_reference_v2"
_DEAL_IDENTITY = "opsflow_order_id"
_COMPANY_ROUTE = "/crm/objects/2026-09/companies/batch/upsert"
_DEAL_ROUTE = "/crm/objects/2026-09/0-3/batch/upsert"


def test_synthetic_contract_and_m9b_partial_recovery() -> None:
    if os.environ.get("OPSFLOW_RUN_HUBSPOT_M9D_LIVE") != "1":
        pytest.skip("set OPSFLOW_RUN_HUBSPOT_M9D_LIVE=1 to run synthetic HubSpot writes")
    asyncio.run(_run_synthetic_contract_and_m9b_recovery())


def test_live_upsert_accepts_omitted_top_level_errors() -> None:
    identity = "OPSFLOW-M9D-FAKE-COMPANY"
    trace = "m9d-fake-company"

    async def scenario() -> str:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETE",
                    "results": [
                        {
                            "id": "450000000001",
                            "objectWriteTraceId": trace,
                            "properties": {
                                "opsflow_customer_reference_v2": identity,
                            },
                        }
                    ],
                },
            )

        async with httpx.AsyncClient(
            base_url=HUBSPOT_API_BASE_URL,
            transport=httpx.MockTransport(handler),
        ) as client:
            return await _upsert(
                client,
                _COMPANY_ROUTE,
                identity=identity,
                identity_property=_COMPANY_IDENTITY,
                properties={_COMPANY_IDENTITY: identity, "name": "Synthetic"},
                trace=trace,
            )

    assert asyncio.run(scenario()) == "450000000001"


def test_live_odoo_stub_uses_distinct_sale_order_ids() -> None:
    async def scenario() -> tuple[OdooOrderReceipt, OdooOrderReceipt]:
        first_id, second_id = UUID(int=1), UUID(int=2)
        odoo = _LiveOdooSteps({first_id, second_id})
        first = await odoo.execute(first_id, OrderSyncStep.ODOO_BRIDGE)
        second = await odoo.execute(second_id, OrderSyncStep.ODOO_BRIDGE)
        assert isinstance(first, OdooOrderReceipt)
        assert isinstance(second, OdooOrderReceipt)
        return first, second

    first, second = asyncio.run(scenario())
    assert first.sale_order_id != second.sale_order_id


class _LiveCustomerProvider:
    def __init__(self, reference: str, name: str) -> None:
        self.reference = reference
        self.name = name

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        return TrustedBusinessData(
            customer_candidates=(TrustedCustomer(self.reference, self.name, True),),
            products_by_line=(),
        )


class _LiveOdooSteps:
    def __init__(self, order_ids: set[UUID]) -> None:
        self.order_ids = order_ids
        self.calls: list[tuple[UUID, OrderSyncStep]] = []
        self.sale_orders = {
            order_id: (9001 + index, f"S{9001 + index}")
            for index, order_id in enumerate(sorted(order_ids, key=str))
        }

    async def execute(self, order_id: UUID, step: OrderSyncStep):
        assert order_id in self.order_ids
        self.calls.append((order_id, step))
        if step is OrderSyncStep.ODOO_LOOKUP:
            return None
        if step is OrderSyncStep.ODOO_BRIDGE:
            sale_order_id, sale_order_name = self.sale_orders[order_id]
            return OdooOrderReceipt(sale_order_id, sale_order_name)
        return OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)


class _LiveStepProbe:
    """Test-only result loss/failure injection around the real executor seam."""

    def __init__(self, hubspot: HubSpotCRMAdapter) -> None:
        self.hubspot = hubspot
        self.calls: list[tuple[UUID, OrderSyncStep]] = []
        self.drop_receipt_once: tuple[UUID, OrderSyncStep] | None = None
        self.fail_before_once: tuple[UUID, OrderSyncStep] | None = None

    async def execute(self, order_id: UUID, step: OrderSyncStep):
        self.calls.append((order_id, step))
        if self.fail_before_once == (order_id, step):
            self.fail_before_once = None
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        result = await self.hubspot.execute(order_id, step)
        if self.drop_receipt_once == (order_id, step) and not isinstance(
            result, OrderSyncStepFailure
        ):
            self.drop_receipt_once = None
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        return result


async def _run_synthetic_contract_and_m9b_recovery() -> None:
    key = os.environ.get("OPSFLOW_HUBSPOT_M9D_SERVICE_KEY")
    pipeline_id = os.environ.get("OPSFLOW_HUBSPOT_M9D_PIPELINE_ID")
    stage_id = os.environ.get("OPSFLOW_HUBSPOT_M9D_INITIAL_STAGE_ID")
    currency = os.environ.get("OPSFLOW_HUBSPOT_M9D_PORTAL_CURRENCY")
    portal_id = os.environ.get("OPSFLOW_HUBSPOT_M9D_EXPECTED_PORTAL_ID")
    confirmed_portal = os.environ.get("OPSFLOW_HUBSPOT_M9D_CONFIRM_PORTAL_ID")
    database_url = os.environ.get("OPSFLOW_HUBSPOT_M9D_OPSFLOW_DATABASE_URL")
    if not all((key, pipeline_id, stage_id, currency, portal_id, confirmed_portal, database_url)):
        pytest.fail("opt-in M9D live variables and an isolated OpsFlow database are required")
    if portal_id != str(_PORTAL_ID) or confirmed_portal != str(_PORTAL_ID):
        pytest.fail("live writes are restricted to the human-approved synthetic portal")
    if (pipeline_id, stage_id, currency) != ("default", "appointmentscheduled", "USD"):
        pytest.fail("live Deal settings differ from the verified synthetic account contract")
    _require_isolated_database(database_url)

    suffix = uuid4().hex[:10].upper()
    company_reference = f"OPSFLOW-M9D-LIVE-{suffix}"
    company_name = f"OpsFlow M9D Synthetic Company {suffix}"
    order_a, order_b = uuid4(), uuid4()
    order_ids = {order_a, order_b}
    po_number_a = f"OPSFLOW-M9D-PO-{suffix}-A"
    po_number_b = f"OPSFLOW-M9D-PO-{suffix}-B"
    deal_name_a = f"PO {po_number_a} - {str(order_a)[:8]}"
    deal_name_b = f"PO {po_number_b} - {str(order_b)[:8]}"
    trace_company = f"m9d-live-company-{suffix.lower()}"
    trace_deal_a = f"m9d-live-deal-a-{suffix.lower()}"
    trace_deal_b = f"m9d-live-deal-b-{suffix.lower()}"
    client = httpx.AsyncClient(
        base_url=HUBSPOT_API_BASE_URL,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=httpx.Timeout(15.0),
    )
    company_id: str | None = None
    deal_ids: dict[UUID, str] = {}
    cleanup_company_id: str | None = None
    engine: AsyncEngine | None = None
    sessions: async_sessionmaker[AsyncSession] | None = None
    adapter: HubSpotCRMAdapter | None = None
    seeded_order_ids: set[UUID] = set()
    try:
        identity = await client.get("/integrations/v1/me")
        _require(identity.status_code == 200, "HubSpot account identity read failed")
        identity_payload = identity.json()
        _require(identity_payload.get("portalId") == _PORTAL_ID, "HubSpot portal ID mismatch")

        # The first Company receipt is deliberately discarded. A same-key replay
        # supplies the ID used by the later independent search and association.
        company_first = await _upsert(
            client,
            _COMPANY_ROUTE,
            identity=company_reference,
            identity_property=_COMPANY_IDENTITY,
            properties={_COMPANY_IDENTITY: company_reference, "name": company_name},
            trace=trace_company,
        )
        cleanup_company_id = company_first
        del company_first
        company_replay = await _upsert(
            client,
            _COMPANY_ROUTE,
            identity=company_reference,
            identity_property=_COMPANY_IDENTITY,
            properties={_COMPANY_IDENTITY: company_reference, "name": company_name},
            trace=trace_company,
        )
        company_id = company_replay
        await _wait_for_single_search_result(
            await _search(client, "companies", _COMPANY_IDENTITY, company_reference),
            client=client,
            object_type="companies",
            identity_property=_COMPANY_IDENTITY,
            identity=company_reference,
            provider_id=company_id,
        )

        updated_company_name = f"{company_name} Updated"
        company_update = await _upsert(
            client,
            _COMPANY_ROUTE,
            identity=company_reference,
            identity_property=_COMPANY_IDENTITY,
            properties={_COMPANY_IDENTITY: company_reference, "name": updated_company_name},
            trace=trace_company,
        )
        _require(company_update == company_id, "Company managed-name update changed provider ID")
        company_record = await _wait_for_single_search_result(
            await _search(client, "companies", _COMPANY_IDENTITY, company_reference),
            client=client,
            object_type="companies",
            identity_property=_COMPANY_IDENTITY,
            identity=company_reference,
            provider_id=company_id,
        )
        _require(
            company_record.get("properties", {}).get("name") == updated_company_name,
            "Company managed-name update was not observed",
        )

        for order_id, po_number, deal_name, trace_deal in (
            (order_a, po_number_a, deal_name_a, trace_deal_a),
            (order_b, po_number_b, deal_name_b, trace_deal_b),
        ):
            deal_properties = {
                _DEAL_IDENTITY: str(order_id),
                "dealname": deal_name,
                "amount": "24.00",
                "pipeline": pipeline_id,
                "dealstage": stage_id,
                "opsflow_currency": currency,
                "opsflow_po_number": po_number,
            }
            _require(
                not _search_results(await _search(client, "0-3", _DEAL_IDENTITY, str(order_id))),
                "random synthetic Deal UUID already exists",
            )
            deal_first = await _upsert(
                client,
                _DEAL_ROUTE,
                identity=str(order_id),
                identity_property=_DEAL_IDENTITY,
                properties=deal_properties,
                trace=trace_deal,
            )
            deal_ids[order_id] = deal_first
            # Do not keep the first Deal response as a local receipt either.
            del deal_first
            deal_replay = await _upsert(
                client,
                _DEAL_ROUTE,
                identity=str(order_id),
                identity_property=_DEAL_IDENTITY,
                properties=deal_properties,
                trace=trace_deal,
            )
            _require(deal_replay == deal_ids[order_id], "Deal replay changed provider ID")
            deal_record = await _wait_for_single_search_result(
                await _search(client, "0-3", _DEAL_IDENTITY, str(order_id)),
                client=client,
                object_type="0-3",
                identity_property=_DEAL_IDENTITY,
                identity=str(order_id),
                provider_id=deal_replay,
            )
            _require(
                deal_record.get("properties", {}).get("amount") == "24.00",
                "Deal amount was not preserved as the approved fixed-point value",
            )
            _require(
                deal_record.get("properties", {}).get("pipeline") == pipeline_id
                and deal_record.get("properties", {}).get("dealstage") == stage_id
                and deal_record.get("properties", {}).get("opsflow_currency") == currency,
                "Deal pipeline, stage, or currency differs from the verified setup",
            )
            update_deal_name = f"{deal_name} Updated"
            deal_update = await _upsert(
                client,
                _DEAL_ROUTE,
                identity=str(order_id),
                identity_property=_DEAL_IDENTITY,
                properties={**deal_properties, "dealname": update_deal_name},
                trace=trace_deal,
            )
            _require(deal_update == deal_ids[order_id], "Deal managed-field update changed ID")
            await _wait_for_single_search_result(
                await _search(client, "0-3", _DEAL_IDENTITY, str(order_id)),
                client=client,
                object_type="0-3",
                identity_property=_DEAL_IDENTITY,
                identity=str(order_id),
                provider_id=deal_ids[order_id],
            )
            await _associate_and_confirm(client, deal_ids[order_id], company_id)
            await _associate_and_confirm(client, deal_ids[order_id], company_id)

        engine, sessions = await _seed_orders(
            database_url,
            (
                (order_a, company_reference, po_number_a, True),
                (order_b, company_reference, po_number_b, False),
            ),
        )
        seeded_order_ids = order_ids.copy()
        settings = Settings(
            _env_file=None,
            database_url=database_url,
            # This is a synthetic placeholder. The live Service Key remains only
            # in the opt-in test process's HTTPX client, never in Settings.
            hubspot_service_key="injected-live-client-placeholder",
            hubspot_pipeline_id=pipeline_id,
            hubspot_initial_stage_id=stage_id,
            hubspot_portal_currency=currency,
            hubspot_expected_portal_id=_PORTAL_ID,
        )
        adapter = HubSpotCRMAdapter(
            settings,
            sessionmaker=sessions,
            business_data_provider=_LiveCustomerProvider(company_reference, company_name),
            client=client,
        )
        probe = _LiveStepProbe(adapter)
        odoo = _LiveOdooSteps(order_ids)
        executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=probe)

        # Order A proves Company response loss/replay and the durable Company
        # boundary before a controlled Deal failure. It spends two retry events.
        probe.drop_receipt_once = (order_a, OrderSyncStep.HUBSPOT_COMPANY)
        first_a = await _execute(sessions, order_a, executor)
        _require(
            first_a.kind is ExecuteNextKind.RETRY_WAIT, "Company response loss was not retryable"
        )
        await _make_eligible(sessions, order_a)
        probe.fail_before_once = (order_a, OrderSyncStep.HUBSPOT_DEAL)
        second_a = await _execute(sessions, order_a, executor)
        _require(
            second_a.kind is ExecuteNextKind.RETRY_WAIT, "controlled Deal failure was not retryable"
        )
        sync_a = await _read_sync(sessions, order_a)
        _require(sync_a.hubspot_company_id == company_id, "Company receipt was not durable")
        _require(sync_a.hubspot_deal_id is None, "Deal ran before its retry boundary")
        await _make_eligible(sessions, order_a)
        third_a = await _execute(sessions, order_a, executor)
        _require(third_a.kind is ExecuteNextKind.COMPLETED, "Order A did not resume at Deal")
        sync_a = await _read_sync(sessions, order_a)
        _require(sync_a.hubspot_company_id == company_id, "Order A Company receipt changed")
        _require(sync_a.hubspot_deal_id == deal_ids[order_a], "Order A Deal receipt mismatch")
        _require(sync_a.hubspot_association_confirmed_at is not None, "Order A association missing")

        # Order B independently proves the Deal receipt boundary before a
        # controlled association failure, also within its own retry generation.
        await _make_eligible(sessions, order_b)
        probe.drop_receipt_once = (order_b, OrderSyncStep.HUBSPOT_DEAL)
        first_b = await _execute(sessions, order_b, executor)
        _require(first_b.kind is ExecuteNextKind.RETRY_WAIT, "Deal response loss was not retryable")
        sync_b = await _read_sync(sessions, order_b)
        _require(sync_b.hubspot_company_id == company_id, "Order B Company receipt was not durable")
        _require(sync_b.hubspot_deal_id is None, "Order B Deal receipt survived simulated loss")
        await _make_eligible(sessions, order_b)
        probe.fail_before_once = (order_b, OrderSyncStep.HUBSPOT_ASSOCIATION)
        second_b = await _execute(sessions, order_b, executor)
        _require(
            second_b.kind is ExecuteNextKind.RETRY_WAIT,
            "controlled association failure was not retryable",
        )
        sync_b = await _read_sync(sessions, order_b)
        _require(sync_b.hubspot_company_id == company_id, "Order B Company receipt changed")
        _require(
            sync_b.hubspot_deal_id == deal_ids[order_b], "Order B Deal receipt was not durable"
        )
        _require(
            sync_b.hubspot_association_confirmed_at is None,
            "Order B association was premature",
        )
        await _make_eligible(sessions, order_b)
        third_b = await _execute(sessions, order_b, executor)
        _require(third_b.kind is ExecuteNextKind.COMPLETED, "Order B did not resume at association")
        sync_b = await _read_sync(sessions, order_b)
        _require(sync_b.hubspot_association_confirmed_at is not None, "Order B association missing")
        await _require_remote_counts(
            client, company_reference, order_a, company_id, deal_ids[order_a]
        )
        await _require_remote_counts(
            client, company_reference, order_b, company_id, deal_ids[order_b]
        )
        _require(
            [step for oid, step in probe.calls if oid == order_a]
            == [
                OrderSyncStep.HUBSPOT_COMPANY,
                OrderSyncStep.HUBSPOT_COMPANY,
                OrderSyncStep.HUBSPOT_DEAL,
                OrderSyncStep.HUBSPOT_DEAL,
                OrderSyncStep.HUBSPOT_ASSOCIATION,
            ],
            "Order A did not resume from the first missing durable receipt",
        )
        _require(
            [step for oid, step in probe.calls if oid == order_b]
            == [
                OrderSyncStep.HUBSPOT_COMPANY,
                OrderSyncStep.HUBSPOT_DEAL,
                OrderSyncStep.HUBSPOT_DEAL,
                OrderSyncStep.HUBSPOT_ASSOCIATION,
                OrderSyncStep.HUBSPOT_ASSOCIATION,
            ],
            "Order B unexpectedly repeated a durable provider receipt",
        )
        for order_id in (order_a, order_b):
            _require(
                [step for oid, step in odoo.calls if oid == order_id]
                == [OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE],
                "durable Odoo receipt caused Odoo to repeat",
            )
    finally:
        if seeded_order_ids and sessions is not None and engine is not None:
            for order_id in seeded_order_ids:
                await _delete_seeded_order(sessions, order_id)
            await engine.dispose()
        cleanup_company_id = cleanup_company_id or company_id
        if not client.is_closed:
            for cleanup_deal_id in deal_ids.values():
                await _archive_record(client, "0-3", cleanup_deal_id)
        if cleanup_company_id is not None and not client.is_closed:
            await _archive_record(client, "companies", cleanup_company_id)
        if adapter is not None:
            await adapter.aclose()
        if not client.is_closed:
            await client.aclose()


async def _upsert(
    client: httpx.AsyncClient,
    path: str,
    *,
    identity: str,
    identity_property: str,
    properties: dict[str, str],
    trace: str,
) -> str:
    response = await client.post(
        path,
        json={
            "inputs": [
                {
                    "id": identity,
                    "idProperty": identity_property,
                    "properties": properties,
                    "objectWriteTraceId": trace,
                }
            ]
        },
    )
    _require(response.status_code in (200, 207), "HubSpot upsert HTTP status was not accepted")
    payload = _json_object(response)
    _require(payload.get("status") == "COMPLETE", "HubSpot upsert was not terminal COMPLETE")
    _require(payload.get("errors", []) == [], "HubSpot upsert reported item errors")
    results = payload.get("results")
    _require(type(results) is list and len(results) == 1, "HubSpot upsert result was ambiguous")
    result = results[0]
    _require(type(result) is dict, "HubSpot upsert result was malformed")
    _require(result.get("objectWriteTraceId") == trace, "HubSpot result trace did not correlate")
    result_properties = result.get("properties")
    _require(type(result_properties) is dict, "HubSpot result properties were malformed")
    _require(
        result_properties.get(identity_property) == identity,
        "HubSpot result stable identity did not correlate",
    )
    provider_id = result.get("id")
    _require(type(provider_id) is str and bool(provider_id), "HubSpot provider ID was malformed")
    return provider_id


async def _search(
    client: httpx.AsyncClient,
    object_type: str,
    identity_property: str,
    identity: str,
) -> dict[str, object]:
    properties = (
        [identity_property, "name"]
        if object_type == "companies"
        else [
            identity_property,
            "dealname",
            "amount",
            "pipeline",
            "dealstage",
            "opsflow_currency",
            "opsflow_po_number",
        ]
    )
    response = await client.post(
        f"/crm/objects/2026-09/{object_type}/search",
        json={
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": identity_property,
                            "operator": "EQ",
                            "value": identity,
                        }
                    ]
                }
            ],
            "properties": properties,
            "limit": 10,
        },
    )
    _require(response.status_code == 200, "HubSpot synthetic identity search failed")
    return _json_object(response)


def _search_results(payload: dict[str, object]) -> list[dict[str, object]]:
    results = payload.get("results")
    _require(type(results) is list, "HubSpot search results were malformed")
    return [item for item in results if type(item) is dict]


def _require_single_search_result(
    payload: dict[str, object],
    identity_property: str,
    identity: str,
    provider_id: str,
) -> dict[str, object]:
    results = _search_results(payload)
    _require(len(results) == 1, "HubSpot stable identity did not resolve to exactly one record")
    result = results[0]
    _require(result.get("id") == provider_id, "HubSpot search ID differed from the upsert receipt")
    properties = result.get("properties")
    _require(type(properties) is dict, "HubSpot search properties were malformed")
    _require(
        properties.get(identity_property) == identity,
        "HubSpot search returned a different stable identity",
    )
    return result


async def _wait_for_single_search_result(
    _initial_payload: dict[str, object],
    *,
    client: httpx.AsyncClient,
    object_type: str,
    identity_property: str,
    identity: str,
    provider_id: str,
) -> dict[str, object]:
    payload = _initial_payload
    for attempt in range(20):
        results = _search_results(payload)
        if len(results) == 1:
            return _require_single_search_result(
                payload,
                identity_property,
                identity,
                provider_id,
            )
        _require(not results, "HubSpot stable identity resolved to duplicate records")
        if attempt < 19:
            await asyncio.sleep(0.25)
            payload = await _search(client, object_type, identity_property, identity)
    pytest.fail("HubSpot stable identity did not become visible within the bounded test window")


async def _associate_and_confirm(
    client: httpx.AsyncClient,
    deal_id: str,
    company_id: str,
) -> None:
    response = await client.put(
        f"/crm/objects/2026-09/deal/{deal_id}/associations/default/company/{company_id}"
    )
    _require(response.status_code == 200, "HubSpot association write failed")
    payload = _json_object(response)
    _require(payload.get("status") == "COMPLETE", "HubSpot association was not complete")
    results = payload.get("results")
    _require(
        type(results) is list
        and any(
            type(item) is dict
            and type(item.get("from")) is dict
            and item["from"].get("id") == deal_id
            and type(item.get("to")) is dict
            and item["to"].get("id") == company_id
            and type(item.get("associationSpec")) is dict
            and item["associationSpec"].get("associationCategory") == "HUBSPOT_DEFINED"
            and item["associationSpec"].get("associationTypeId") == 341
            for item in results
        ),
        "HubSpot association result did not confirm directed type 341",
    )
    read = await client.get(f"/crm/objects/2026-09/deal/{deal_id}/associations/company")
    _require(read.status_code == 200, "HubSpot association verification read failed")
    read_payload = _json_object(read)
    read_results = read_payload.get("results")
    _require(type(read_results) is list, "HubSpot association read was malformed")
    matches = [
        item
        for item in read_results
        if type(item) is dict
        and str(item.get("toObjectId")) == company_id
        and type(item.get("associationTypes")) is list
        and any(
            type(association_type) is dict and association_type.get("typeId") == 341
            for association_type in item["associationTypes"]
        )
    ]
    _require(len(matches) == 1, "default Deal-to-Company relation was not uniquely confirmed")


async def _require_remote_counts(
    client: httpx.AsyncClient,
    company_reference: str,
    order_id: UUID,
    company_id: str,
    deal_id: str,
) -> None:
    company_result = await _wait_for_single_search_result(
        await _search(client, "companies", _COMPANY_IDENTITY, company_reference),
        client=client,
        object_type="companies",
        identity_property=_COMPANY_IDENTITY,
        identity=company_reference,
        provider_id=company_id,
    )
    deal_result = await _wait_for_single_search_result(
        await _search(client, "0-3", _DEAL_IDENTITY, str(order_id)),
        client=client,
        object_type="0-3",
        identity_property=_DEAL_IDENTITY,
        identity=str(order_id),
        provider_id=deal_id,
    )
    _require(company_result["id"] == company_id, "duplicate synthetic Company exists")
    _require(deal_result["id"] == deal_id, "duplicate synthetic Deal exists")
    _require(type(company_result.get("id")) is str, "Company record ID was not opaque text")


async def _seed_orders(
    database_url: str,
    orders: tuple[tuple[UUID, str, str, bool], ...],
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    _run_alembic(database_url, "upgrade", "head")
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        for order_id, customer_reference, po_number, initially_eligible in orders:
            session.add(
                OrderModel(
                    id=order_id,
                    customer_reference=customer_reference,
                    po_number=po_number,
                    order_date=None,
                    requested_delivery_date=None,
                    currency="USD",
                    state=OrderState.APPROVED.value,
                    failure_origin=None,
                    created_at=now,
                )
            )
            await session.flush()
            session.add(
                OrderLineModel(
                    id=uuid4(),
                    order_id=order_id,
                    position=0,
                    sku="SYNTHETIC-LIVE-SKU",
                    description="Synthetic HubSpot test line",
                    quantity=Decimal("2"),
                    submitted_price=Decimal("12.00"),
                    trusted_catalogue_price=Decimal("12.00"),
                )
            )
            session.add(
                OrderSyncModel(
                    order_id=order_id,
                    claim_token=None,
                    claim_expires_at=None,
                    attempt_count=0,
                    retry_generation=0,
                    next_attempt_at=(
                        datetime(1970, 1, 1, tzinfo=UTC)
                        if initially_eligible
                        else now + timedelta(days=1)
                    ),
                    odoo_sale_order_id=None,
                    odoo_sale_order_name=None,
                    hubspot_company_id=None,
                    hubspot_deal_id=None,
                    hubspot_association_confirmed_at=None,
                    in_flight_step=None,
                    last_failure_step=None,
                    last_failure_code=None,
                    last_attempt_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
    return engine, sessions


async def _execute(sessions: async_sessionmaker[AsyncSession], order_id: UUID, executor: object):
    async with sessions() as session:
        return await execute_next_order_sync(session, executor)


async def _make_eligible(sessions: async_sessionmaker[AsyncSession], order_id: UUID) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            update(OrderSyncModel)
            .where(OrderSyncModel.order_id == order_id)
            .values(next_attempt_at=func.now() - timedelta(seconds=1))
        )


async def _read_sync(sessions: async_sessionmaker[AsyncSession], order_id: UUID) -> OrderSyncModel:
    async with sessions() as session:
        sync = await session.get(OrderSyncModel, order_id)
        _require(sync is not None, "M9B durable sync row disappeared")
        return sync


async def _delete_seeded_order(sessions: async_sessionmaker[AsyncSession], order_id: UUID) -> None:
    async with sessions() as session, session.begin():
        await session.execute(delete(OrderModel).where(OrderModel.id == order_id))


async def _archive_record(client: httpx.AsyncClient, object_type: str, provider_id: str) -> None:
    response = await client.delete(f"/crm/objects/2026-09/{object_type}/{provider_id}")
    _require(response.status_code in (204, 404), "synthetic HubSpot record archive failed")


def _require_isolated_database(database_url: str) -> None:
    try:
        target = make_url(database_url)
        development = make_url(Settings().database_url)
    except Exception:
        pytest.fail("M9D live tests require valid PostgreSQL database URLs")
    _require(target.get_backend_name() == "postgresql", "M9D live database must be PostgreSQL")
    _require(bool(target.database), "M9D live database name is required")
    _require(
        target.database != development.database,
        "M9D live tests refuse the development OpsFlow database",
    )


def _run_alembic(database_url: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["OPSFLOW_DATABASE_URL"] = database_url
    environment.pop("OPSFLOW_HUBSPOT_M9D_SERVICE_KEY", None)
    environment.pop("OPSFLOW_HUBSPOT_SERVICE_KEY", None)
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except (ValueError, UnicodeDecodeError):
        pytest.fail("HubSpot returned a malformed JSON response")
    _require(type(payload) is dict, "HubSpot response must be a JSON object")
    return payload


def _require(condition: object, message: str) -> None:
    if not condition:
        pytest.fail(message)
