"""Fixed Phase 9 routing between the existing ERP and CRM adapters."""

from dataclasses import dataclass
from uuid import UUID

from opsflow.order_sync.contracts import (
    OrderSyncFailureCode,
    OrderSyncStep,
    OrderSyncStepExecutor,
    OrderSyncStepFailure,
    OrderSyncStepResult,
)


@dataclass(frozen=True, slots=True)
class Phase9OrderSyncExecutor:
    """Route the five approved Phase 9 steps without owning sync state."""

    odoo: OrderSyncStepExecutor
    hubspot: OrderSyncStepExecutor

    async def execute(self, order_id: UUID, step: OrderSyncStep) -> OrderSyncStepResult:
        """Dispatch a single step to its provider adapter."""

        if step in (OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE):
            return await self.odoo.execute(order_id, step)
        if step in (
            OrderSyncStep.HUBSPOT_COMPANY,
            OrderSyncStep.HUBSPOT_DEAL,
            OrderSyncStep.HUBSPOT_ASSOCIATION,
        ):
            return await self.hubspot.execute(order_id, step)
        return OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)
