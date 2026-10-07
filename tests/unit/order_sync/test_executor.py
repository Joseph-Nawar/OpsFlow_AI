"""Fixed M9D composition routing tests."""

import asyncio
import json
import logging
from uuid import uuid4

import pytest

from opsflow.observability.runtime import Observability, reset_observability, set_observability
from opsflow.order_sync.contracts import (
    HubSpotCompanyReceipt,
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepFailure,
)
from opsflow.order_sync.executor import Phase9OrderSyncExecutor


class _Executor:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[object, object]] = []

    async def execute(self, order_id: object, step: object) -> object:
        self.calls.append((order_id, step))
        return self.result


def test_fixed_executor_routes_only_the_existing_provider_steps() -> None:
    order_id = uuid4()
    odoo_result = object()
    hubspot_result = HubSpotCompanyReceipt("company-synthetic-1")
    odoo = _Executor(odoo_result)
    hubspot = _Executor(hubspot_result)
    executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=hubspot)

    async def exercise() -> list[object]:
        return [
            await executor.execute(order_id, OrderSyncStep.ODOO_LOOKUP),
            await executor.execute(order_id, OrderSyncStep.ODOO_BRIDGE),
            await executor.execute(order_id, OrderSyncStep.HUBSPOT_COMPANY),
            await executor.execute(order_id, OrderSyncStep.HUBSPOT_DEAL),
            await executor.execute(order_id, OrderSyncStep.HUBSPOT_ASSOCIATION),
        ]

    assert asyncio.run(exercise()) == [
        odoo_result,
        odoo_result,
        hubspot_result,
        hubspot_result,
        hubspot_result,
    ]
    assert [step for _identity, step in odoo.calls] == [
        OrderSyncStep.ODOO_LOOKUP,
        OrderSyncStep.ODOO_BRIDGE,
    ]
    assert [step for _identity, step in hubspot.calls] == [
        OrderSyncStep.HUBSPOT_COMPANY,
        OrderSyncStep.HUBSPOT_DEAL,
        OrderSyncStep.HUBSPOT_ASSOCIATION,
    ]


def test_fixed_executor_bounds_unknown_step_without_dispatch() -> None:
    odoo = _Executor(None)
    hubspot = _Executor(None)
    executor = Phase9OrderSyncExecutor(odoo=odoo, hubspot=hubspot)

    result = asyncio.run(executor.execute(uuid4(), "UNAPPROVED_STEP"))

    assert result == OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
    assert not odoo.calls
    assert not hubspot.calls


def test_executor_observes_one_provider_operation_without_changing_result() -> None:
    async def exercise() -> tuple[object, Observability]:
        result = HubSpotCompanyReceipt("company-synthetic-2")
        observer = Observability({"hubspot": "CONFIGURED"})
        token = set_observability(observer)
        try:
            executor = Phase9OrderSyncExecutor(_Executor(None), _Executor(result))
            returned = await executor.execute(uuid4(), OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            reset_observability(token)
        return returned, observer

    returned, observer = asyncio.run(exercise())
    assert returned == HubSpotCompanyReceipt("company-synthetic-2")
    snapshot = observer.metrics.snapshot()
    assert snapshot["counters"]["order_sync_steps_total"]
    assert observer.integrations.snapshot()["hubspot"]["observation"] == "HEALTHY"


def test_business_order_sync_failure_does_not_claim_provider_unavailable() -> None:
    async def exercise() -> Observability:
        observer = Observability({"odoo": "CONFIGURED"})
        token = set_observability(observer)
        try:
            executor = Phase9OrderSyncExecutor(
                _Executor(OrderSyncStepFailure(OrderSyncFailureCode.INVENTORY_INSUFFICIENT)),
                _Executor(None),
            )
            result = await executor.execute(uuid4(), OrderSyncStep.ODOO_LOOKUP)
            assert result == OrderSyncStepFailure(OrderSyncFailureCode.INVENTORY_INSUFFICIENT)
        finally:
            reset_observability(token)
        return observer

    observer = asyncio.run(exercise())
    assert observer.integrations.snapshot()["odoo"]["observation"] == "NOT_OBSERVED"


def test_provider_unavailable_order_sync_failure_observes_provider_failure() -> None:
    async def exercise() -> Observability:
        observer = Observability({"odoo": "CONFIGURED"})
        token = set_observability(observer)
        try:
            executor = Phase9OrderSyncExecutor(
                _Executor(OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)),
                _Executor(None),
            )
            result = await executor.execute(uuid4(), OrderSyncStep.ODOO_LOOKUP)
            assert result == OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        finally:
            reset_observability(token)
        return observer

    observer = asyncio.run(exercise())
    assert observer.integrations.snapshot()["odoo"]["observation"] == "UNAVAILABLE"


def test_phase9_provider_metrics_are_recorded_once_without_duplicate_provider_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def exercise() -> tuple[object, Observability]:
        result = HubSpotCompanyReceipt("company-synthetic-3")
        observer = Observability({"hubspot": "CONFIGURED"})
        token = set_observability(observer)
        try:
            executor = Phase9OrderSyncExecutor(_Executor(None), _Executor(result))
            returned = await executor.execute(uuid4(), OrderSyncStep.HUBSPOT_COMPANY)
        finally:
            reset_observability(token)
        return returned, observer

    with caplog.at_level(logging.INFO, logger="opsflow.observability"):
        returned, observer = asyncio.run(exercise())
    assert returned == HubSpotCompanyReceipt("company-synthetic-3")
    snapshot = observer.metrics.snapshot()
    assert sum(snapshot["counters"]["order_sync_steps_total"].values()) == 1
    assert sum(snapshot["counters"]["provider_calls_total"].values()) == 1
    assert (
        sum(item["count"] for item in snapshot["histograms"]["provider_duration_ms"].values()) == 1
    )
    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "opsflow.observability"
    ]
    assert [event["event"] for event in events] == ["order_sync_step_outcome"]


def test_odoo_phase9_provider_metrics_are_recorded_once() -> None:
    async def exercise() -> tuple[object, Observability]:
        result = OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
        observer = Observability({"odoo": "CONFIGURED"})
        token = set_observability(observer)
        try:
            executor = Phase9OrderSyncExecutor(_Executor(result), _Executor(None))
            returned = await executor.execute(uuid4(), OrderSyncStep.ODOO_BRIDGE)
        finally:
            reset_observability(token)
        return returned, observer

    returned, observer = asyncio.run(exercise())
    assert returned == OrderSyncStepFailure(OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
    snapshot = observer.metrics.snapshot()
    assert sum(snapshot["counters"]["order_sync_steps_total"].values()) == 1
    assert sum(snapshot["counters"]["provider_calls_total"].values()) == 1
    assert (
        sum(item["count"] for item in snapshot["histograms"]["provider_duration_ms"].values()) == 1
    )
