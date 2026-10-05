"""Fixed M9D composition routing tests."""

import asyncio
from uuid import uuid4

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
