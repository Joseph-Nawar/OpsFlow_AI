"""Narrow response contract for the orchestration intake boundary."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from opsflow.domain import OrderState


class OrchestrationIntakeResponse(BaseModel):
    """Authoritative order state without internal pipeline details."""

    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    idempotent_replay: bool
