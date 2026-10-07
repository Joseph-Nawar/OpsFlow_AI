"""Narrow response contract for the orchestration intake boundary."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opsflow.domain import OrderState
from opsflow.orchestration.ownership import INTAKE_OWNERSHIP_LEASE_SECONDS
from opsflow.order_sync.contracts import ExecuteNextKind


class OrchestrationIntakeResponse(BaseModel):
    """Authoritative order state without internal pipeline details."""

    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    idempotent_replay: bool
    retry_after_seconds: int | None = Field(
        default=None,
        ge=1,
        le=INTAKE_OWNERSHIP_LEASE_SECONDS,
    )


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
