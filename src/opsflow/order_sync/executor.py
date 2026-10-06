"""Fixed Phase 9 routing between the existing ERP and CRM adapters."""

import time
from contextlib import suppress
from dataclasses import dataclass
from uuid import UUID

from opsflow.observability.runtime import current_observability, duration_ms
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

        provider: str | None = None
        if step in (OrderSyncStep.ODOO_LOOKUP, OrderSyncStep.ODOO_BRIDGE):
            provider = "odoo"
            selected = self.odoo
        elif step in (
            OrderSyncStep.HUBSPOT_COMPANY,
            OrderSyncStep.HUBSPOT_DEAL,
            OrderSyncStep.HUBSPOT_ASSOCIATION,
        ):
            provider = "hubspot"
            selected = self.hubspot
        else:
            return OrderSyncStepFailure(OrderSyncFailureCode.INTEGRATION_CONFIG)

        started_ns = time.perf_counter_ns()
        try:
            result = await selected.execute(order_id, step)
        except Exception:
            observer = current_observability()
            if observer is not None:
                with suppress(Exception):
                    observer.order_sync_outcome(
                        provider=provider,
                        step=step.value,
                        success=False,
                        duration_ms=duration_ms(started_ns),
                        order_id=str(order_id),
                        failure_code="PROVIDER_UNAVAILABLE",
                    )
            raise

        failure_code = result.code.value if isinstance(result, OrderSyncStepFailure) else None
        observer = current_observability()
        if observer is not None:
            with suppress(Exception):
                observer.order_sync_outcome(
                    provider=provider,
                    step=step.value,
                    success=not isinstance(result, OrderSyncStepFailure),
                    duration_ms=duration_ms(started_ns),
                    order_id=str(order_id),
                    failure_code=failure_code,
                )
        return result
