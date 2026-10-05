"""Narrow, bounded HubSpot Company and Deal operations for Phase 9."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import cast
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opsflow.application.errors import OrderNotFoundError
from opsflow.application.orders import get_order
from opsflow.domain import Order, OrderState
from opsflow.order_sync.contracts import (
    HubSpotAssociationReceipt,
    HubSpotCompanyReceipt,
    HubSpotDealReceipt,
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepFailure,
    OrderSyncStepResult,
)
from opsflow.persistence.models import OrderSyncModel
from opsflow.settings import Settings
from opsflow.validation.business_data import BusinessDataProvider
from opsflow.validation.models import BusinessDataLookupRequest, TrustedCustomer

HUBSPOT_API_VERSION = "2026-09"
HUBSPOT_API_BASE_URL = "https://api.hubapi.com"
HUBSPOT_COMPANY_IDENTITY = "opsflow_customer_reference_v2"
HUBSPOT_DEAL_IDENTITY = "opsflow_order_id"
HUBSPOT_APPROVED_PIPELINE_ID = "default"
HUBSPOT_APPROVED_INITIAL_STAGE_ID = "appointmentscheduled"
HUBSPOT_APPROVED_PORTAL_CURRENCY = "USD"
_HUBSPOT_REQUEST_TIMEOUT_SECONDS = 15.0
_MAX_RETRY_AFTER_SECONDS = 3600
_MAX_EXTERNAL_ID_LENGTH = 256
_MAX_DEAL_NAME_LENGTH = 128
_RETRY_AFTER_SECONDS = re.compile(r"[0-9]+", flags=re.ASCII)


class _HubSpotFailure(Exception):
    """One provider condition reduced to an existing bounded M9B result."""

    def __init__(
        self,
        code: OrderSyncFailureCode,
        retry_after: timedelta | None = None,
    ) -> None:
        self.code = code
        self.retry_after = retry_after
        super().__init__(code.value)


class HubSpotCRMAdapter:
    """Call only the approved HubSpot Company, Deal, and association routes."""

    def __init__(
        self,
        settings: Settings,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        business_data_provider: BusinessDataProvider,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        required = (
            settings.hubspot_service_key,
            settings.hubspot_pipeline_id,
            settings.hubspot_initial_stage_id,
            settings.hubspot_portal_currency,
            settings.hubspot_expected_portal_id,
        )
        if any(value is None for value in required):
            raise ValueError("complete HubSpot settings are required")
        if transport is not None and client is not None:
            raise ValueError("provide either an HTTPX transport or client, not both")
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._business_data_provider = business_data_provider
        if client is not None:
            self._client = client
        else:
            assert settings.hubspot_service_key is not None
            self._client = httpx.AsyncClient(
                base_url=HUBSPOT_API_BASE_URL,
                headers={
                    "Authorization": f"Bearer {settings.hubspot_service_key.get_secret_value()}",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(_HUBSPOT_REQUEST_TIMEOUT_SECONDS),
                transport=transport,
            )

    async def aclose(self) -> None:
        """Release the shared HTTPX connection pool."""

        await self._client.aclose()

    async def execute(self, order_id: UUID, step: OrderSyncStep) -> OrderSyncStepResult:
        """Execute one HubSpot checkpoint without local writes or retained state."""

        if step not in (
            OrderSyncStep.HUBSPOT_COMPANY,
            OrderSyncStep.HUBSPOT_DEAL,
            OrderSyncStep.HUBSPOT_ASSOCIATION,
        ):
            return OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        try:
            snapshot = await self._load_snapshot(order_id)
            order = snapshot.order
            if order.state not in (OrderState.APPROVED, OrderState.SYNCING):
                raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_REJECTED)
            await self._verify_account()
            if step is OrderSyncStep.HUBSPOT_COMPANY:
                if snapshot.odoo_sale_order_id is None or order.customer_reference is None:
                    raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
                return await self._upsert_company(order)
            if step is OrderSyncStep.HUBSPOT_DEAL:
                if snapshot.hubspot_company_id is None:
                    raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
                return await self._upsert_deal(order)
            if snapshot.hubspot_company_id is None or snapshot.hubspot_deal_id is None:
                raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
            return await self._associate(snapshot.hubspot_deal_id, snapshot.hubspot_company_id)
        except _HubSpotFailure as failure:
            return OrderSyncStepFailure(failure.code, failure.retry_after)
        except OrderNotFoundError:
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        except Exception:
            # Database/provider exception details can contain business data or tracebacks.
            return OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)

    async def _load_snapshot(self, order_id: UUID) -> _SyncSnapshot:
        async with self._sessionmaker() as session:
            persisted_order = await get_order(session, order_id)
            sync_row = await session.get(OrderSyncModel, order_id)
            if sync_row is None:
                raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
            return _SyncSnapshot(
                order=persisted_order.order,
                odoo_sale_order_id=sync_row.odoo_sale_order_id,
                hubspot_company_id=sync_row.hubspot_company_id,
                hubspot_deal_id=sync_row.hubspot_deal_id,
            )

    async def _verify_account(self) -> None:
        response = await self._request("GET", "/integrations/v1/me")
        try:
            payload = _json_object(response)
            portal_id = payload.get("portalId")
            if type(portal_id) is str and portal_id.isascii() and portal_id.isdigit():
                portal_id = int(portal_id)
        except _HubSpotFailure:
            raise
        except (ValueError, TypeError):
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE) from None
        if type(portal_id) is not int or portal_id <= 0:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        if portal_id != self._settings.hubspot_expected_portal_id:
            raise _HubSpotFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)

    async def _upsert_company(self, order: Order) -> HubSpotCompanyReceipt:
        reference = order.customer_reference
        if reference is None:
            raise _HubSpotFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING)
        try:
            data = await self._business_data_provider.get_validation_data(
                BusinessDataLookupRequest(
                    customer_reference=reference,
                    customer_name=None,
                    skus=(),
                )
            )
        except Exception:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE) from None
        customers = data.customer_candidates
        if not customers:
            raise _HubSpotFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING)
        if len(customers) != 1:
            raise _HubSpotFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_AMBIGUOUS)
        customer = customers[0]
        if type(customer) is not TrustedCustomer or customer.reference != reference:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        if not customer.active:
            raise _HubSpotFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING)
        result_id = await self._upsert(
            object_path="companies",
            identity_property=HUBSPOT_COMPANY_IDENTITY,
            identity=reference,
            properties={HUBSPOT_COMPANY_IDENTITY: reference, "name": customer.name},
            trace=_trace_id(order.id, OrderSyncStep.HUBSPOT_COMPANY),
        )
        return HubSpotCompanyReceipt(result_id)

    async def _upsert_deal(self, order: Order) -> HubSpotDealReceipt:
        pipeline_id = self._settings.hubspot_pipeline_id
        stage_id = self._settings.hubspot_initial_stage_id
        portal_currency = self._settings.hubspot_portal_currency
        if pipeline_id is None or stage_id is None or portal_currency is None:
            raise _HubSpotFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        if (
            pipeline_id != HUBSPOT_APPROVED_PIPELINE_ID
            or stage_id != HUBSPOT_APPROVED_INITIAL_STAGE_ID
            or portal_currency != HUBSPOT_APPROVED_PORTAL_CURRENCY
        ):
            raise _HubSpotFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        if order.currency != portal_currency:
            raise _HubSpotFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        amount = _deal_amount(order)
        properties = {
            HUBSPOT_DEAL_IDENTITY: str(order.id),
            "dealname": _deal_name(order),
            "amount": amount,
            "pipeline": pipeline_id,
            "dealstage": stage_id,
            "opsflow_currency": portal_currency,
            "opsflow_po_number": order.po_number or "",
        }
        existing_id = await self._find_existing_deal(order.id, pipeline_id, stage_id)
        if existing_id is None:
            response = await self._request(
                "POST",
                f"/crm/objects/{HUBSPOT_API_VERSION}/0-3",
                json={"properties": properties},
                allow_201=True,
                allow_400_validation_error=True,
            )
            if response.status_code == 400:
                if _is_deal_identity_conflict(response, str(order.id)):
                    # Search may lag or another create may win after our read.
                    # A fresh M9B attempt will read the stable identity again.
                    raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
                raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_REJECTED)
            payload = _json_object(response)
            result_id = _provider_id(payload.get("id"))
            result_properties = _object(payload.get("properties"))
            if (
                result_id is None
                or result_properties.get(HUBSPOT_DEAL_IDENTITY) != str(order.id)
                or result_properties.get("pipeline") != pipeline_id
                or result_properties.get("dealstage") != stage_id
            ):
                raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
            return HubSpotDealReceipt(result_id)

        response = await self._request(
            "PATCH",
            f"/crm/objects/{HUBSPOT_API_VERSION}/0-3/{existing_id}",
            json={
                "properties": {
                    HUBSPOT_DEAL_IDENTITY: str(order.id),
                    "dealname": properties["dealname"],
                    "amount": amount,
                    "opsflow_currency": portal_currency,
                    "opsflow_po_number": order.po_number or "",
                }
            },
        )
        update_result = _json_object(response)
        if _provider_id(update_result.get("id")) != existing_id:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        current = await self._request(
            "GET",
            f"/crm/objects/{HUBSPOT_API_VERSION}/0-3/{existing_id}",
            params={"properties": f"{HUBSPOT_DEAL_IDENTITY},pipeline,dealstage"},
        )
        current_payload = _json_object(current)
        current_properties = _object(current_payload.get("properties"))
        if _provider_id(current_payload.get("id")) != existing_id or current_properties.get(
            HUBSPOT_DEAL_IDENTITY
        ) != str(order.id):
            raise _HubSpotFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        if (
            current_properties.get("pipeline") != pipeline_id
            or current_properties.get("dealstage") != stage_id
        ):
            raise _HubSpotFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        return HubSpotDealReceipt(existing_id)

    async def _find_existing_deal(
        self,
        order_id: UUID,
        expected_pipeline: str,
        expected_stage: str,
    ) -> str | None:
        response = await self._request(
            "POST",
            f"/crm/objects/{HUBSPOT_API_VERSION}/0-3/search",
            json={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": HUBSPOT_DEAL_IDENTITY,
                                "operator": "EQ",
                                "value": str(order_id),
                            }
                        ]
                    }
                ],
                "properties": [HUBSPOT_DEAL_IDENTITY, "pipeline", "dealstage"],
                "limit": 2,
            },
        )
        payload = _json_object(response)
        results = payload.get("results")
        total = payload.get("total")
        if type(results) is not list or type(total) is not int:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        if total == 0 and not results:
            return None
        if total != 1 or len(results) != 1:
            raise _HubSpotFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        record = _object(results[0])
        record_id = _provider_id(record.get("id"))
        properties = _object(record.get("properties"))
        if (
            record_id is None
            or properties.get(HUBSPOT_DEAL_IDENTITY) != str(order_id)
            or type(properties.get("pipeline")) is not str
            or type(properties.get("dealstage")) is not str
        ):
            raise _HubSpotFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        if properties["pipeline"] != expected_pipeline or properties["dealstage"] != expected_stage:
            raise _HubSpotFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        return record_id

    async def _upsert(
        self,
        *,
        object_path: str,
        identity_property: str,
        identity: str,
        properties: dict[str, str],
        trace: str,
    ) -> str:
        response = await self._request(
            "POST",
            f"/crm/objects/{HUBSPOT_API_VERSION}/{object_path}/batch/upsert",
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
            allow_207=True,
        )
        return _parse_upsert_response(
            response,
            identity_property=identity_property,
            identity=identity,
            trace=trace,
        )

    async def _associate(self, deal_id: str, company_id: str) -> HubSpotAssociationReceipt:
        path = (
            f"/crm/objects/{HUBSPOT_API_VERSION}/deal/{deal_id}/associations/default/company/"
            f"{company_id}"
        )
        response = await self._request("PUT", path)
        payload = _json_object(response)
        if payload.get("status") == "PENDING" or payload.get("status") == "PROCESSING":
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_PENDING)
        if payload.get("status") == "CANCELED":
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_REJECTED)
        if payload.get("status") != "COMPLETE":
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        results = payload.get("results")
        if type(results) is not list or not any(
            _association_result_matches(item, deal_id, company_id) for item in results
        ):
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        read_response = await self._request(
            "GET",
            f"/crm/objects/{HUBSPOT_API_VERSION}/deal/{deal_id}/associations/company",
        )
        read_payload = _json_object(read_response)
        read_results = read_payload.get("results")
        if type(read_results) is not list:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        matching = [item for item in read_results if _association_read_matches(item, company_id)]
        if len(matching) != 1:
            raise _HubSpotFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
        return HubSpotAssociationReceipt(datetime.now(UTC))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: dict[str, str] | None = None,
        allow_207: bool = False,
        allow_201: bool = False,
        allow_400_validation_error: bool = False,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                json=json,
                params=params,
                timeout=httpx.Timeout(_HUBSPOT_REQUEST_TIMEOUT_SECONDS),
            )
        except httpx.TransportError:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE) from None
        if response.status_code == 400 and allow_400_validation_error:
            return response
        if response.status_code in (401, 403, 404, 422):
            raise _HubSpotFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
        if response.status_code == 429:
            delay = parse_retry_after(response.headers.get("Retry-After"))
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_RATE_LIMIT, delay)
        if response.status_code >= 500:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        if response.status_code >= 400:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_REJECTED)
        if response.status_code == 207 and not allow_207:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        if response.status_code not in (200, 207) and not (
            allow_201 and response.status_code == 201
        ):
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        return response


@dataclass(frozen=True, slots=True)
class _SyncSnapshot:
    order: Order
    odoo_sale_order_id: int | None
    hubspot_company_id: str | None
    hubspot_deal_id: str | None


def parse_retry_after(
    value: str | None,
    *,
    now: datetime | None = None,
) -> timedelta | None:
    """Parse and bound the provider Retry-After value without sleeping."""

    if value is None or not value or value != value.strip():
        return None
    if _RETRY_AFTER_SECONDS.fullmatch(value) is not None:
        seconds_text = value.lstrip("0") or "0"
        if len(seconds_text) > 4 or (
            len(seconds_text) == 4 and seconds_text > str(_MAX_RETRY_AFTER_SECONDS)
        ):
            return timedelta(seconds=_MAX_RETRY_AFTER_SECONDS)
        return timedelta(seconds=int(seconds_text))
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        return None
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        return None
    delay = (retry_at.astimezone(UTC) - current_time.astimezone(UTC)).total_seconds()
    if delay <= 0:
        return None
    return timedelta(seconds=min(delay, _MAX_RETRY_AFTER_SECONDS))


def _parse_upsert_response(
    response: httpx.Response,
    *,
    identity_property: str,
    identity: str,
    trace: str,
) -> str:
    try:
        payload = _object(response.json())
    except (ValueError, TypeError):
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE) from None
    status = payload.get("status")
    if status in ("PENDING", "PROCESSING"):
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_PENDING)
    if status == "CANCELED":
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_REJECTED)
    if status != "COMPLETE":
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    errors = payload.get("errors", [])
    if type(errors) is not list:
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    if errors:
        raise _HubSpotFailure(_item_error_code(errors, trace))
    results = payload.get("results")
    if type(results) is not list or len(results) != 1:
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    result = _object(results[0])
    properties = _object(result.get("properties"))
    result_id = _provider_id(result.get("id"))
    if (
        result_id is None
        or result.get("objectWriteTraceId") != trace
        or properties.get(identity_property) != identity
    ):
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return result_id


def _is_deal_identity_conflict(response: httpx.Response, identity: str) -> bool:
    """Recognize the live-verified unique-property create rejection only."""

    try:
        payload = _json_object(response)
    except (ValueError, TypeError):
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE) from None
    message = payload.get("message")
    identity_clause = f"propertyName={HUBSPOT_DEAL_IDENTITY}, value={identity}}}"
    return (
        payload.get("category") == "VALIDATION_ERROR"
        and type(message) is str
        and message.startswith("Cannot set PropertyValueCoordinates{")
        and identity_clause in message
        and message.endswith("already has that value.")
    )


def _item_error_code(errors: list[object], trace: str) -> OrderSyncFailureCode:
    if len(errors) != 1:
        return OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE
    error = errors[0]
    if type(error) is not dict:
        return OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE
    if error.get("objectWriteTraceId") != trace:
        return OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE
    category = error.get("category")
    code = error.get("code")
    safe_category = category if type(category) is str else code
    if safe_category in {"UNAUTHORIZED", "MISSING_SCOPE", "PERMISSION_DENIED"}:
        return OrderSyncFailureCode.INTEGRATION_CONFIG
    if safe_category in {"VALIDATION_ERROR", "INVALID_INPUT", "CONFLICT"}:
        return OrderSyncFailureCode.PROVIDER_REJECTED
    return OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE


def _association_result_matches(item: object, deal_id: str, company_id: str) -> bool:
    if type(item) is not dict:
        return False
    from_object = item.get("from")
    to_object = item.get("to")
    association_spec = item.get("associationSpec")
    if (
        type(from_object) is not dict
        or type(to_object) is not dict
        or type(association_spec) is not dict
    ):
        return False
    return (
        from_object.get("id") == deal_id
        and to_object.get("id") == company_id
        and association_spec.get("associationCategory") == "HUBSPOT_DEFINED"
        and association_spec.get("associationTypeId") == 341
    )


def _association_read_matches(item: object, company_id: str) -> bool:
    if type(item) is not dict or str(item.get("toObjectId")) != company_id:
        return False
    types = item.get("associationTypes")
    return type(types) is list and any(
        type(association_type) is dict and association_type.get("typeId") == 341
        for association_type in types
    )


def _trace_id(order_id: UUID, step: OrderSyncStep) -> str:
    return f"opsflow-{step.value.lower()}-{order_id.hex}"


def _deal_name(order: Order) -> str:
    order_suffix = str(order.id)[:8]
    po_number = order.po_number or "Order"
    suffix = f" - {order_suffix}"
    prefix = f"PO {po_number}"
    return f"{prefix[: _MAX_DEAL_NAME_LENGTH - len(suffix)]}{suffix}"


def _deal_amount(order: Order) -> str:
    total = Decimal("0")
    if not order.lines:
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    for line in order.lines:
        if line.submitted_price is None:
            raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
        total += line.quantity * line.submitted_price
    return format(total, "f")


def _provider_id(value: object) -> str | None:
    if type(value) is not str or not value or value != value.strip():
        return None
    if len(value) > _MAX_EXTERNAL_ID_LENGTH:
        return None
    return value


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    return cast(dict[str, object], value)


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        return _object(response.json())
    except (ValueError, TypeError, UnicodeDecodeError):
        raise _HubSpotFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE) from None
