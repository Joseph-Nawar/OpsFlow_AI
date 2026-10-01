"""Provider-free HubSpot contract tests using HTTPX fake transports."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from opsflow.domain import Order, OrderLine, OrderState
from opsflow.hubspot import parse_retry_after
from opsflow.order_sync.contracts import (
    HubSpotAssociationReceipt,
    HubSpotCompanyReceipt,
    HubSpotDealReceipt,
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepFailure,
)
from opsflow.persistence.repositories import PersistedOrder
from opsflow.settings import Settings
from opsflow.validation.models import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
)

PORTAL_ID = 149461984
COMPANY_PROPERTY = "opsflow_customer_reference_v2"
DEAL_PROPERTY = "opsflow_order_id"
SERVICE_KEY_SENTINEL = "synthetic-hubspot-service-key-sentinel"
RAW_BODY_SENTINEL = "HUBSPOT_RAW_RESPONSE_SENTINEL_DO_NOT_LEAK"
TRACE_SENTINEL = "HUBSPOT_TRACEBACK_SENTINEL_DO_NOT_LEAK"
CRM_SENTINEL = "Synthetic Confidential Project Name"


class _FakeSession:
    def __init__(self, sync: object) -> None:
        self.sync = sync
        self.active = False

    async def __aenter__(self) -> "_FakeSession":
        self.active = True
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.active = False

    async def get(self, _model: object, _identity: UUID) -> object:
        return self.sync

    async def rollback(self) -> None:
        self.active = False


class _FakeSessionMaker:
    def __init__(self, sync: object) -> None:
        self.sync = sync
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        session = _FakeSession(self.sync)
        self.sessions.append(session)
        return session


class _CustomerProvider:
    def __init__(
        self,
        *,
        reference: str = "CUST-001",
        name: str = "OpsFlow Synthetic Co",
        active: bool = True,
    ) -> None:
        self.reference = reference
        self.name = name
        self.active = active
        self.requests: list[BusinessDataLookupRequest] = []

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        self.requests.append(request)
        return TrustedBusinessData(
            customer_candidates=(TrustedCustomer(self.reference, self.name, self.active),),
            products_by_line=(),
        )


def _settings(
    *,
    pipeline_id: str = "default",
    stage_id: str = "appointmentscheduled",
    currency: str = "USD",
) -> Settings:
    return Settings(
        _env_file=None,
        hubspot_service_key=SERVICE_KEY_SENTINEL,
        hubspot_pipeline_id=pipeline_id,
        hubspot_initial_stage_id=stage_id,
        hubspot_portal_currency=currency,
        hubspot_expected_portal_id=PORTAL_ID,
    )


def _order(
    *,
    order_id: UUID | None = None,
    currency: str | None = "USD",
    customer_reference: str | None = "CUST-001",
    po_number: str | None = "PO-SYNTHETIC-9",
    state: OrderState = OrderState.SYNCING,
    lines: tuple[OrderLine, ...] | None = None,
) -> Order:
    identity = order_id or UUID("749c6773-1245-4cfe-a8a8-86d90cb045c3")
    return Order(
        id=identity,
        customer_reference=customer_reference,
        po_number=po_number,
        order_date=None,
        requested_delivery_date=None,
        currency=currency,
        state=state,
        lines=lines
        or (
            OrderLine(
                uuid4(),
                "SKU-SYNTHETIC-1",
                CRM_SENTINEL,
                Decimal("2"),
                Decimal("12.00"),
                Decimal("12.00"),
            ),
        ),
    )


def _sync(
    order_id: UUID,
    *,
    company_id: str | None = None,
    deal_id: str | None = None,
    association_at: datetime | None = None,
    last_failure_step: OrderSyncStep | None = None,
    last_failure_code: OrderSyncFailureCode | None = None,
) -> object:
    return type(
        "SyncSnapshot",
        (),
        {
            "order_id": order_id,
            "odoo_sale_order_id": 9001,
            "hubspot_company_id": company_id,
            "hubspot_deal_id": deal_id,
            "hubspot_association_confirmed_at": association_at,
            "last_failure_step": last_failure_step,
            "last_failure_code": last_failure_code,
        },
    )()


def _adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    order: Order,
    sync: object | None = None,
    handler,
    provider: _CustomerProvider | None = None,
    settings: Settings | None = None,
):
    import opsflow.hubspot as hubspot

    sessions = _FakeSessionMaker(sync or _sync(order.id))

    async def get_order(_session: object, order_id: UUID) -> PersistedOrder:
        assert order_id == order.id
        return PersistedOrder(order, datetime.now(UTC), ())

    monkeypatch.setattr(hubspot, "get_order", get_order)
    adapter = hubspot.HubSpotCRMAdapter(
        settings or _settings(),
        sessionmaker=sessions,
        business_data_provider=provider or _CustomerProvider(),
        transport=httpx.MockTransport(handler),
    )
    return adapter, sessions


def _json(request: httpx.Request) -> object:
    return json.loads(request.content) if request.content else None


def _identity_response() -> httpx.Response:
    return httpx.Response(200, json={"portalId": PORTAL_ID})


def _upsert_response(
    request: httpx.Request,
    *,
    provider_id: str,
    identity_name: str,
    identity: str,
):
    body = _json(request)
    item = body["inputs"][0]
    return httpx.Response(
        200,
        json={
            "completedAt": "2026-10-01T10:00:00Z",
            "startedAt": "2026-10-01T10:00:00Z",
            "status": "COMPLETE",
            "results": [
                {
                    "id": provider_id,
                    "new": True,
                    "properties": {identity_name: identity},
                    "objectWriteTraceId": item["objectWriteTraceId"],
                }
            ],
            "errors": [],
        },
    )


def test_company_upsert_uses_v2_identity_and_trusted_name(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []
    provider = _CustomerProvider(name="Trusted Synthetic Company")

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        return _upsert_response(
            request,
            provider_id="450254569667",
            identity_name=COMPANY_PROPERTY,
            identity="CUST-001",
        )

    order = _order()
    adapter, sessions = _adapter(monkeypatch, order=order, handler=handle, provider=provider)

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == HubSpotCompanyReceipt("450254569667")
    assert [request.url.path for request in requests] == [
        "/integrations/v1/me",
        "/crm/objects/2026-09/companies/batch/upsert",
    ]
    body = _json(requests[1])
    item = body["inputs"][0]
    assert len(body["inputs"]) == 1
    assert item["id"] == "CUST-001"
    assert item["idProperty"] == COMPANY_PROPERTY
    assert item["properties"] == {
        COMPANY_PROPERTY: "CUST-001",
        "name": "Trusted Synthetic Company",
    }
    assert item["objectWriteTraceId"]
    assert COMPANY_PROPERTY not in " ".join(str(request.url) for request in requests[:1])
    assert provider.requests[0].customer_reference == "CUST-001"
    assert provider.requests[0].skus == ()
    assert not any(session.active for session in sessions.sessions)


def test_company_replay_updates_only_trusted_name_on_same_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert_bodies: list[object] = []
    provider = _CustomerProvider(name="First Trusted Name")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        upsert_bodies.append(_json(request))
        return _upsert_response(
            request,
            provider_id="450254569667",
            identity_name=COMPANY_PROPERTY,
            identity="CUST-001",
        )

    order = _order()
    adapter, _sessions = _adapter(monkeypatch, order=order, handler=handle, provider=provider)

    async def exercise() -> list[object]:
        try:
            first = await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
            provider.name = "Updated Trusted Name"
            second = await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
            return [first, second]
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == [
        HubSpotCompanyReceipt("450254569667"),
        HubSpotCompanyReceipt("450254569667"),
    ]
    assert len(upsert_bodies) == 2
    assert [body["inputs"][0]["properties"] for body in upsert_bodies] == [
        {COMPANY_PROPERTY: "CUST-001", "name": "First Trusted Name"},
        {COMPANY_PROPERTY: "CUST-001", "name": "Updated Trusted Name"},
    ]


def test_ineligible_customer_fails_before_company_write(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        pytest.fail("ineligible customer must not produce a Company write")

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        handler=handle,
        provider=_CustomerProvider(active=False),
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == OrderSyncStepFailure(OrderSyncFailureCode.TRUSTED_CUSTOMER_MISSING)
    assert [request.url.path for request in requests] == ["/integrations/v1/me"]


def test_wrong_portal_fails_before_company_write(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"portalId": 999999999, "type": "DEVELOPER_TEST"})

    order = _order()
    adapter, _sessions = _adapter(monkeypatch, order=order, handler=handle)

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
    assert len(requests) == 1
    assert requests[0].url.path == "/integrations/v1/me"


def test_deal_create_uses_exact_decimal_amount_and_initial_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "results": []})
        return _upsert_response(
            request,
            provider_id="524327563504",
            identity_name=DEAL_PROPERTY,
            identity=str(order.id),
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == HubSpotDealReceipt("524327563504")
    assert [request.url.path for request in requests] == [
        "/integrations/v1/me",
        "/crm/objects/2026-09/0-3/search",
        "/crm/objects/2026-09/0-3/batch/upsert",
    ]
    body = _json(requests[2])
    item = body["inputs"][0]
    assert len(body["inputs"]) == 1
    assert item["id"] == str(order.id)
    assert item["idProperty"] == DEAL_PROPERTY
    assert item["properties"] == {
        DEAL_PROPERTY: str(order.id),
        "dealname": "PO PO-SYNTHETIC-9 - 749c6773",
        "amount": "24.00",
        "pipeline": "default",
        "dealstage": "appointmentscheduled",
        "opsflow_currency": "USD",
        "opsflow_po_number": "PO-SYNTHETIC-9",
    }


def test_deal_stage_progression_is_not_reset_during_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        return httpx.Response(
            200,
            json={
                "total": 1,
                "results": [
                    {
                        "id": "524327563504",
                        "properties": {
                            DEAL_PROPERTY: str(order.id),
                            "pipeline": "default",
                            "dealstage": "qualifiedtobuy",
                        },
                    }
                ],
            },
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == OrderSyncStepFailure(OrderSyncFailureCode.RECONCILIATION_REQUIRED)
    assert [request.method for request in requests] == ["GET", "POST"]
    assert requests[-1].url.path.endswith("/search")


def test_existing_deal_in_another_pipeline_is_not_rewritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "results": [
                        {
                            "id": "deal-opaque-1",
                            "properties": {
                                DEAL_PROPERTY: str(order.id),
                                "pipeline": "different-pipeline",
                                "dealstage": "appointmentscheduled",
                            },
                        }
                    ],
                },
            )
        pytest.fail("existing Deal in another pipeline must not be updated")

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(
        OrderSyncFailureCode.RECONCILIATION_REQUIRED
    )
    assert requests[-1].url.path.endswith("/search")


def test_unverified_deal_setup_fails_closed_before_search_or_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        pytest.fail("unverified Deal configuration must not reach a business route")

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
        settings=_settings(pipeline_id="unverified-pipeline"),
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
    assert [request.url.path for request in requests] == ["/integrations/v1/me"]


def test_order_currency_mismatch_fails_before_deal_provider_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        pytest.fail("currency mismatch must fail before provider read/write")

    order = _order(currency="EUR")
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
    assert [request.url.path for request in requests] == ["/integrations/v1/me"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("PENDING", OrderSyncFailureCode.PROVIDER_PENDING),
        ("PROCESSING", OrderSyncFailureCode.PROVIDER_PENDING),
        ("CANCELED", OrderSyncFailureCode.PROVIDER_REJECTED),
    ],
)
def test_nonterminal_or_canceled_upsert_never_returns_receipt(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: OrderSyncFailureCode,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "results": []})
        return httpx.Response(200, json={"status": status, "results": [], "errors": []})

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(expected)


def test_http_207_requires_one_intended_success_without_item_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "results": []})
        item = _json(request)["inputs"][0]
        return httpx.Response(
            207,
            json={
                "status": "COMPLETE",
                "results": [
                    {
                        "id": "524327563504",
                        "properties": {DEAL_PROPERTY: str(order.id)},
                        "objectWriteTraceId": item["objectWriteTraceId"],
                    }
                ],
                "errors": [{"category": "VALIDATION_ERROR", "objectWriteTraceId": "other-item"}],
            },
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(
        OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE
    )


def test_429_uses_bounded_retry_after_and_does_not_leak_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        return httpx.Response(429, headers={"Retry-After": "7200"}, text=RAW_BODY_SENTINEL)

    order = _order()
    adapter, _sessions = _adapter(monkeypatch, order=order, handler=handle)

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == OrderSyncStepFailure(
        OrderSyncFailureCode.PROVIDER_RATE_LIMIT,
        timedelta(seconds=3600),
    )
    assert RAW_BODY_SENTINEL not in repr(result)
    assert parse_retry_after("-1") is None
    assert parse_retry_after("7200") == timedelta(seconds=3600)


def test_retry_after_accepts_future_http_date_and_rejects_past_date() -> None:
    now = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)

    assert parse_retry_after("Thu, 01 Oct 2026 10:00:30 GMT", now=now) == timedelta(seconds=30)
    assert parse_retry_after("Thu, 01 Oct 2026 09:59:30 GMT", now=now) is None
    assert parse_retry_after("not-a-date", now=now) is None


def test_retry_after_clamps_extremely_large_delta_without_unbounded_integer_parse() -> None:
    assert parse_retry_after("9" * 5_000) == timedelta(seconds=3600)


@pytest.mark.parametrize(
    ("result_changes", "expected"),
    [
        ({"objectWriteTraceId": "other-trace"}, OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE),
        (
            {"properties": {DEAL_PROPERTY: "different-id"}},
            OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE,
        ),
    ],
)
def test_upsert_rejects_uncorrelated_or_wrong_identity_result(
    monkeypatch: pytest.MonkeyPatch,
    result_changes: dict[str, object],
    expected: OrderSyncFailureCode,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "results": []})
        item = _json(request)["inputs"][0]
        result = {
            "id": "524327563504",
            "properties": {DEAL_PROPERTY: str(order.id)},
            "objectWriteTraceId": item["objectWriteTraceId"],
        }
        result.update(result_changes)
        return httpx.Response(200, json={"status": "COMPLETE", "results": [result], "errors": []})

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(expected)


def test_upsert_rejects_multiple_intended_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "results": []})
        item = _json(request)["inputs"][0]
        result = {
            "id": "deal-opaque-1",
            "properties": {DEAL_PROPERTY: str(order.id)},
            "objectWriteTraceId": item["objectWriteTraceId"],
        }
        return httpx.Response(
            200,
            json={"status": "COMPLETE", "results": [result, result], "errors": []},
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(
        OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE
    )


def test_207_correlated_item_error_prevents_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "results": []})
        item = _json(request)["inputs"][0]
        return httpx.Response(
            207,
            json={
                "status": "COMPLETE",
                "results": [
                    {
                        "id": "524327563504",
                        "properties": {DEAL_PROPERTY: str(order.id)},
                        "objectWriteTraceId": item["objectWriteTraceId"],
                    }
                ],
                "errors": [
                    {
                        "category": "VALIDATION_ERROR",
                        "objectWriteTraceId": item["objectWriteTraceId"],
                    }
                ],
            },
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_REJECTED)


def test_http_207_single_correlated_success_returns_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "results": []})
        item = _json(request)["inputs"][0]
        return httpx.Response(
            207,
            json={
                "status": "COMPLETE",
                "results": [
                    {
                        "id": "deal-opaque-207",
                        "properties": {DEAL_PROPERTY: str(order.id)},
                        "objectWriteTraceId": item["objectWriteTraceId"],
                    }
                ],
                "errors": [],
            },
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == HubSpotDealReceipt("deal-opaque-207")


@pytest.mark.parametrize(
    ("http_status", "expected"),
    [
        (400, OrderSyncFailureCode.PROVIDER_REJECTED),
        (401, OrderSyncFailureCode.INTEGRATION_CONFIG),
        (403, OrderSyncFailureCode.INTEGRATION_CONFIG),
        (404, OrderSyncFailureCode.INTEGRATION_CONFIG),
        (422, OrderSyncFailureCode.INTEGRATION_CONFIG),
        (500, OrderSyncFailureCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_provider_http_status_maps_to_bounded_failure(
    monkeypatch: pytest.MonkeyPatch,
    http_status: int,
    expected: OrderSyncFailureCode,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        return httpx.Response(http_status, text=RAW_BODY_SENTINEL)

    order = _order()
    adapter, _sessions = _adapter(monkeypatch, order=order, handler=handle)

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == OrderSyncStepFailure(expected)
    assert RAW_BODY_SENTINEL not in repr(result)


def test_transport_timeout_is_retryable_and_raw_details_are_discarded(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        raise httpx.ReadTimeout(TRACE_SENTINEL, request=request)

    order = _order()
    adapter, _sessions = _adapter(monkeypatch, order=order, handler=handle)

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
    assert SERVICE_KEY_SENTINEL not in repr(result)
    assert TRACE_SENTINEL not in repr(result)
    assert TRACE_SENTINEL not in caplog.text


def test_cancellation_propagates_and_adapter_client_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        raise asyncio.CancelledError

    order = _order()
    adapter, _sessions = _adapter(monkeypatch, order=order, handler=handle)

    async def exercise() -> None:
        try:
            await adapter.execute(order.id, OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            await adapter.aclose()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(exercise())
    assert adapter._client.is_closed


def test_association_receipt_requires_confirmed_default_type_341(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.method == "PUT":
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETE",
                    "results": [
                        {
                            "from": {"id": "524327563504"},
                            "to": {"id": "450254569667"},
                            "associationSpec": {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": 341,
                            },
                        },
                        {
                            "from": {"id": "450254569667"},
                            "to": {"id": "524327563504"},
                            "associationSpec": {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": 342,
                            },
                        },
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "toObjectId": "450254569667",
                        "associationTypes": [
                            {"category": "HUBSPOT_DEFINED", "typeId": 341},
                            {"category": "HUBSPOT_DEFINED", "typeId": 5},
                        ],
                    }
                ]
            },
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667", deal_id="524327563504"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_ASSOCIATION)
        finally:
            await adapter.aclose()

    assert isinstance(asyncio.run(exercise()), HubSpotAssociationReceipt)
    assert requests[1].method == "PUT"
    assert requests[1].url.path == (
        "/crm/objects/2026-09/deal/524327563504/associations/default/company/450254569667"
    )
    assert _json(requests[1]) is None
    assert requests[2].method == "GET"
    assert requests[2].url.path == "/crm/objects/2026-09/deal/524327563504/associations/company"


def test_association_without_default_type_341_returns_no_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.method == "PUT":
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETE",
                    "results": [
                        {
                            "from": {"id": "524327563504"},
                            "to": {"id": "450254569667"},
                            "associationSpec": {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": 341,
                            },
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "toObjectId": "450254569667",
                        "associationTypes": [{"typeId": 342}],
                    }
                ]
            },
        )

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667", deal_id="524327563504"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_ASSOCIATION)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(
        OrderSyncFailureCode.RECONCILIATION_REQUIRED
    )


def test_malformed_deal_search_is_invalid_response_not_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        return httpx.Response(200, text=RAW_BODY_SENTINEL)

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    result = asyncio.run(exercise())

    assert result == OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE)
    assert RAW_BODY_SENTINEL not in repr(result)


def test_http_207_is_not_accepted_for_unique_deal_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/integrations/v1/me":
            return _identity_response()
        if request.url.path.endswith("/search"):
            return httpx.Response(207, json={"total": 0, "results": []})
        pytest.fail("an ambiguous search status must prevent the upsert")

    order = _order()
    adapter, _sessions = _adapter(
        monkeypatch,
        order=order,
        sync=_sync(order.id, company_id="450254569667"),
        handler=handle,
    )

    async def exercise() -> object:
        try:
            return await adapter.execute(order.id, OrderSyncStep.HUBSPOT_DEAL)
        finally:
            await adapter.aclose()

    assert asyncio.run(exercise()) == OrderSyncStepFailure(
        OrderSyncFailureCode.PROVIDER_INVALID_RESPONSE
    )
