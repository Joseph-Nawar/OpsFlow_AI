"""Narrow response contract for the orchestration intake boundary."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from opsflow.domain import OrderState
from opsflow.order_sync.contracts import ExecuteNextKind


class OrchestrationIntakeResponse(BaseModel):
    """Authoritative order state without internal pipeline details."""

    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    idempotent_replay: bool


class OrderSyncExecutionResponse(BaseModel):
    """Sanitized outcome with only OpsFlow identity and authoritative state."""

    model_config = ConfigDict(extra="forbid")

    result: ExecuteNextKind
    order_id: UUID | None
    state: OrderState | None

    @model_validator(mode="after")
    def require_identity_and_state_together(self) -> "OrderSyncExecutionResponse":
        if (self.order_id is None) != (self.state is None):
            raise ValueError("order_id and state must be both present or both absent")
        return self
