"""Opt-in HubSpot 2026-09 synthetic account and M9B recovery proof."""

import asyncio
import json
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
_DEAL_CREATE_ROUTE = "/crm/objects/2026-09/0-3"


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


class _DealStageRaceTransport(httpx.AsyncBaseTransport):
    """Hold one real existing-Deal search while a second client advances it."""

    def __init__(self, order_id: UUID, provider_id: str) -> None:
        self.order_id = str(order_id)
        self.provider_id = provider_id
        self.search_observed = asyncio.Event()
        self.release_search = asyncio.Event()
        self.observed_stage: str | None = None
        self.update_properties: dict[str, object] | None = None
        self.events: list[str] = []
        self._transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.events.append(f"{request.method} {request.url.path}")
        if request.method == "POST" and request.url.path == "/crm/objects/2026-09/0-3/search":
            body = json.loads(request.content)
            identity = body["filterGroups"][0]["filters"][0]["value"]
            if identity == self.order_id:
                response = await self._transport.handle_async_request(request)
                content = await response.aread()
                status_code = response.status_code
                content_type = response.headers.get("content-type", "application/json")
                try:
                    payload = json.loads(content)
                    self.observed_stage = payload["results"][0]["properties"]["dealstage"]
                except (ValueError, KeyError, IndexError, TypeError):
                    self.observed_stage = None
                self.events.append(f"search-status={status_code}")
                await response.aclose()
                self.search_observed.set()
                await self.release_search.wait()
                return httpx.Response(
                    status_code,
                    headers={"content-type": content_type},
                    content=content,
                    request=request,
                )
        if request.method == "PATCH" and request.url.path.endswith(f"/{self.provider_id}"):
            body = json.loads(request.content)
            self.update_properties = body.get("properties")
        try:
            response = await self._transport.handle_async_request(request)
        except Exception as exc:
            self.events.append(f"transport-error={type(exc).__name__}")
            raise
        self.events.append(f"response-status={response.status_code}")
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()


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
    order_a, order_b, order_c, race_order_id = uuid4(), uuid4(), uuid4(), uuid4()
    order_ids = {order_a, order_b, order_c}
    po_number_a = f"OPSFLOW-M9D-PO-{suffix}-A"
    po_number_b = f"OPSFLOW-M9D-PO-{suffix}-B"
    trace_company = f"m9d-live-company-{suffix.lower()}"
    probe_order_id = uuid4()
    race_deal_id: str | None = None
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

        # Verify the new create/update contract independently of M9B. A create
        # is create-only; the identity property's uniqueness rejects duplicates.
        probe_properties = {
            _DEAL_IDENTITY: str(probe_order_id),
            "dealname": f"OpsFlow M9D Deal Probe {suffix}",
            "amount": "24.00",
            "pipeline": pipeline_id,
            "dealstage": stage_id,
            "opsflow_currency": currency,
            "opsflow_po_number": f"OPSFLOW-M9D-PROBE-PO-{suffix}",
        }
        probe_deal_id = await _create_deal(client, probe_properties)
        deal_ids[probe_order_id] = probe_deal_id
        duplicate = await client.post(
            _DEAL_CREATE_ROUTE,
            json={"properties": {**probe_properties, "dealname": f"Duplicate {suffix}"}},
        )
        _require(duplicate.status_code == 400, "duplicate Deal create did not fail")
        duplicate_payload = _json_object(duplicate)
        _require(
            duplicate_payload.get("category") == "VALIDATION_ERROR",
            "duplicate Deal create failure category changed",
        )
        probe_after_duplicate = await _wait_for_single_search_result(
            await _search(client, "0-3", _DEAL_IDENTITY, str(probe_order_id)),
            client=client,
            object_type="0-3",
            identity_property=_DEAL_IDENTITY,
            identity=str(probe_order_id),
            provider_id=probe_deal_id,
        )
        _require(
            probe_after_duplicate.get("properties", {}).get("dealname")
            == probe_properties["dealname"],
            "duplicate create modified the existing Deal",
        )
        _require(
            probe_after_duplicate.get("properties", {}).get("dealstage") == stage_id,
            "duplicate create changed the existing Deal stage",
        )
        probe_update = await _patch_deal(
            client,
            probe_deal_id,
            {
                "dealname": f"OpsFlow M9D Deal Probe Updated {suffix}",
                "amount": "25.00",
                "opsflow_po_number": f"OPSFLOW-M9D-PROBE-PO-UPDATED-{suffix}",
            },
        )
        _require(
            _object_properties(probe_update).get("dealname")
            == f"OpsFlow M9D Deal Probe Updated {suffix}",
            "selected managed Deal fields were not updated",
        )
        probe_after_update = await _read_deal(client, probe_deal_id)
        _require(
            _object_properties(probe_after_update).get("dealstage") == stage_id,
            "omitting dealstage did not preserve the remote stage",
        )

        # Seed a third order used by the live read/update race proof. Its
        # synthetic remote Deal is created directly, and the adapter call is
        # paused after the existing-record read until a second client advances it.
        race_deal_id = await _create_deal(
            client,
            {
                _DEAL_IDENTITY: str(race_order_id),
                "dealname": f"OpsFlow M9D Stage Race {suffix}",
                "amount": "24.00",
                "pipeline": pipeline_id,
                "dealstage": stage_id,
                "opsflow_currency": currency,
                "opsflow_po_number": f"OPSFLOW-M9D-RACE-PO-{suffix}",
            },
        )
        deal_ids[race_order_id] = race_deal_id

        engine, sessions = await _seed_orders(
            database_url,
            (
                (order_a, company_reference, po_number_a, True),
                (order_b, company_reference, po_number_b, False),
                (order_c, company_reference, f"{po_number_b}-C", False),
                (race_order_id, company_reference, f"{po_number_b}-RACE", False),
            ),
        )
        seeded_order_ids = order_ids | {race_order_id}
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
        _require(sync_a.hubspot_deal_id is not None, "Order A Deal receipt missing")
        deal_ids[order_a] = str(sync_a.hubspot_deal_id)
        _require(sync_a.hubspot_company_id == company_id, "Order A Company receipt changed")
        _require(sync_a.hubspot_deal_id == deal_ids[order_a], "Order A Deal receipt mismatch")
        _require(sync_a.hubspot_association_confirmed_at is not None, "Order A association missing")

        # Order B proves a lost Deal response can be reconciled by a fresh
        # same-identity invocation. A delayed search-index result may first
        # produce the approved retryable unique-conflict outcome.
        await _make_eligible(sessions, order_b)
        probe.drop_receipt_once = (order_b, OrderSyncStep.HUBSPOT_DEAL)
        first_b = await _execute(sessions, order_b, executor)
        _require(first_b.kind is ExecuteNextKind.RETRY_WAIT, "Deal response loss was not retryable")
        sync_b = await _read_sync(sessions, order_b)
        _require(sync_b.hubspot_company_id == company_id, "Order B Company receipt was not durable")
        _require(sync_b.hubspot_deal_id is None, "Order B Deal receipt survived simulated loss")
        second_b = await _resume_after_create_race(sessions, order_b, executor, client)
        _require(second_b.kind is ExecuteNextKind.COMPLETED, "Order B did not reconcile its Deal")
        sync_b = await _read_sync(sessions, order_b)
        deal_ids[order_b] = str(sync_b.hubspot_deal_id)
        _require(sync_b.hubspot_association_confirmed_at is not None, "Order B association missing")

        # Order C proves the durable Deal receipt boundary before a controlled
        # association failure, independently of the lost-response retry above.
        await _make_eligible(sessions, order_c)
        probe.fail_before_once = (order_c, OrderSyncStep.HUBSPOT_ASSOCIATION)
        first_c = await _execute(sessions, order_c, executor)
        _require(first_c.kind is ExecuteNextKind.RETRY_WAIT, "association fault was not retryable")
        sync_c = await _read_sync(sessions, order_c)
        deal_ids[order_c] = str(sync_c.hubspot_deal_id)
        _require(sync_c.hubspot_company_id == company_id, "Order C Company receipt changed")
        _require(sync_c.hubspot_deal_id == deal_ids[order_c], "Order C Deal receipt changed")
        await _make_eligible(sessions, order_c)
        final_c = await _execute(sessions, order_c, executor)
        _require(final_c.kind is ExecuteNextKind.COMPLETED, "Order C did not resume at association")
        _require(
            (await _read_sync(sessions, order_c)).hubspot_association_confirmed_at is not None,
            "Order C association receipt missing",
        )

        # Complete the controlled existing-read/update race: the adapter has
        # already observed the initial stage but is paused before it can return
        # that read to production code. An independent client advances the Deal.
        await _mark_syncing_with_company(sessions, race_order_id, company_id)
        race_transport = _DealStageRaceTransport(race_order_id, race_deal_id)
        race_client = httpx.AsyncClient(
            base_url=HUBSPOT_API_BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=httpx.Timeout(15.0),
            transport=race_transport,
        )
        race_adapter = HubSpotCRMAdapter(
            settings,
            sessionmaker=sessions,
            business_data_provider=_LiveCustomerProvider(company_reference, company_name),
            client=race_client,
        )
        race_task = asyncio.create_task(
            race_adapter.execute(race_order_id, OrderSyncStep.HUBSPOT_DEAL)
        )
        try:
            await asyncio.wait_for(race_transport.search_observed.wait(), timeout=20)
            _require(
                race_transport.observed_stage == stage_id,
                "adapter did not read the synthetic Deal at its initial stage",
            )
            progressed = await _advance_deal_stage(client, race_deal_id, "qualifiedtobuy")
            _require(
                _object_properties(progressed).get("dealstage") == "qualifiedtobuy",
                "HubSpot did not accept the synthetic progressed stage",
            )
            progressed_read = await _read_deal(client, race_deal_id)
            _require(
                _object_properties(progressed_read).get("dealstage") == "qualifiedtobuy",
                "independent read did not observe human-progressed stage",
            )
        finally:
            race_transport.release_search.set()
        race_result = await race_task
        race_code = getattr(getattr(race_result, "code", None), "value", None)
        _require(
            isinstance(race_result, OrderSyncStepFailure)
            and race_result.code is OrderSyncFailureCode.RECONCILIATION_REQUIRED,
            "stage-race execution returned "
            f"{type(race_result).__name__}:{race_code}; update fields were "
            f"{sorted(race_transport.update_properties or {})}; "
            f"provider events={race_transport.events}",
        )
        _require(
            race_transport.update_properties is not None
            and "dealstage" not in race_transport.update_properties,
            "existing Deal update included the human-owned stage",
        )
        race_final = await _read_deal(client, race_deal_id)
        _require(
            _object_properties(race_final).get("dealstage") == "qualifiedtobuy",
            "OpsFlow regressed the concurrently progressed Deal stage",
        )
        await race_adapter.aclose()
        await _require_remote_counts(
            client, company_reference, order_a, company_id, deal_ids[order_a]
        )
        await _require_remote_counts(
            client, company_reference, order_b, company_id, deal_ids[order_b]
        )
        await _require_remote_counts(
            client, company_reference, order_c, company_id, deal_ids[order_c]
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
        order_b_steps = [step for oid, step in probe.calls if oid == order_b]
        _require(
            order_b_steps.count(OrderSyncStep.HUBSPOT_COMPANY) == 1
            and order_b_steps.count(OrderSyncStep.HUBSPOT_DEAL) in (2, 3)
            and order_b_steps.count(OrderSyncStep.HUBSPOT_ASSOCIATION) == 1,
            "Order B did not resume through stable-identity Deal reconciliation",
        )
        _require(
            [step for oid, step in probe.calls if oid == order_c]
            == [
                OrderSyncStep.HUBSPOT_COMPANY,
                OrderSyncStep.HUBSPOT_DEAL,
                OrderSyncStep.HUBSPOT_ASSOCIATION,
                OrderSyncStep.HUBSPOT_ASSOCIATION,
            ],
            "Order C unexpectedly repeated a durable Company or Deal receipt",
        )
        for order_id in (order_a, order_b, order_c):
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
            cleanup_deal_ids = set(deal_ids.values())
            for synthetic_order_id in (*order_ids, race_order_id, probe_order_id):
                try:
                    cleanup = await _search(client, "0-3", _DEAL_IDENTITY, str(synthetic_order_id))
                    cleanup_deal_ids.update(
                        result["id"]
                        for result in _search_results(cleanup)
                        if type(result.get("id")) is str
                    )
                except Exception:
                    # Cleanup continues for every known synthetic provider ID.
                    pass
            for cleanup_deal_id in cleanup_deal_ids:
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


async def _create_deal(client: httpx.AsyncClient, properties: dict[str, str]) -> str:
    response = await client.post(_DEAL_CREATE_ROUTE, json={"properties": properties})
    _require(response.status_code == 201, "HubSpot Deal create HTTP status was not 201")
    payload = _json_object(response)
    provider_id = payload.get("id")
    result_properties = payload.get("properties")
    _require(type(provider_id) is str and bool(provider_id), "HubSpot Deal create ID was malformed")
    _require(type(result_properties) is dict, "HubSpot Deal create properties were malformed")
    _require(
        result_properties.get(_DEAL_IDENTITY) == properties[_DEAL_IDENTITY]
        and result_properties.get("pipeline") == properties["pipeline"]
        and result_properties.get("dealstage") == properties["dealstage"],
        "HubSpot Deal create response did not confirm identity and initial workflow state",
    )
    return provider_id


async def _patch_deal(
    client: httpx.AsyncClient,
    provider_id: str,
    properties: dict[str, str],
) -> dict[str, object]:
    _require("dealstage" not in properties, "existing Deal update must omit dealstage")
    response = await client.patch(
        f"/crm/objects/2026-09/0-3/{provider_id}",
        json={"properties": properties},
    )
    _require(response.status_code == 200, "HubSpot Deal update HTTP status was not 200")
    payload = _json_object(response)
    _require(payload.get("id") == provider_id, "HubSpot Deal update changed provider ID")
    return payload


async def _advance_deal_stage(
    client: httpx.AsyncClient,
    provider_id: str,
    stage_id: str,
) -> dict[str, object]:
    """Advance only the synthetic Deal as the concurrent human actor."""

    response = await client.patch(
        f"/crm/objects/2026-09/0-3/{provider_id}",
        json={"properties": {"dealstage": stage_id}},
    )
    _require(response.status_code == 200, "synthetic human Deal stage advance failed")
    payload = _json_object(response)
    _require(payload.get("id") == provider_id, "human stage update changed Deal ID")
    return payload


async def _read_deal(
    client: httpx.AsyncClient,
    provider_id: str,
    properties: tuple[str, ...] = (
        _DEAL_IDENTITY,
        "dealname",
        "amount",
        "pipeline",
        "dealstage",
        "opsflow_currency",
        "opsflow_po_number",
    ),
) -> dict[str, object]:
    response = await client.get(
        f"/crm/objects/2026-09/0-3/{provider_id}",
        params={"properties": ",".join(properties)},
    )
    _require(response.status_code == 200, "HubSpot Deal read by ID failed")
    payload = _json_object(response)
    _require(payload.get("id") == provider_id, "HubSpot Deal read returned a different ID")
    _require(type(payload.get("properties")) is dict, "HubSpot Deal read properties were malformed")
    return payload


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


def _object_properties(payload: dict[str, object]) -> dict[str, object]:
    properties = payload.get("properties")
    _require(type(properties) is dict, "HubSpot object properties were malformed")
    return properties


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


async def _resume_after_create_race(
    sessions: async_sessionmaker[AsyncSession],
    order_id: UUID,
    executor: object,
    client: httpx.AsyncClient,
):
    result = None
    for attempt in range(2):
        await _make_eligible(sessions, order_id)
        result = await _execute(sessions, order_id, executor)
        if result.kind is ExecuteNextKind.COMPLETED:
            return result
        if attempt == 1 or result.kind is not ExecuteNextKind.RETRY_WAIT:
            return result
        # If create committed but search indexing lagged, the unique-key
        # conflict is retryable. Wait only in this test harness for a fresh
        # read to expose the winner before the next bounded M9B invocation.
        payload = await _search(client, "0-3", _DEAL_IDENTITY, str(order_id))
        for poll in range(20):
            results = _search_results(payload)
            if len(results) == 1:
                provider_id = results[0].get("id")
                _require(type(provider_id) is str, "reconciled Deal ID was malformed")
                _require_single_search_result(
                    payload,
                    _DEAL_IDENTITY,
                    str(order_id),
                    provider_id,
                )
                break
            _require(not results, "lost-response identity resolved to duplicate Deals")
            if poll < 19:
                await asyncio.sleep(0.25)
                payload = await _search(client, "0-3", _DEAL_IDENTITY, str(order_id))
        else:
            pytest.fail("lost-response Deal did not become visible for same-identity replay")
    return result


async def _mark_syncing_with_company(
    sessions: async_sessionmaker[AsyncSession], order_id: UUID, company_id: str
) -> None:
    async with sessions() as session, session.begin():
        order = await session.get(OrderModel, order_id)
        sync = await session.get(OrderSyncModel, order_id)
        _require(order is not None and sync is not None, "race order seed is missing")
        order.state = OrderState.SYNCING.value
        sync.hubspot_company_id = company_id


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
