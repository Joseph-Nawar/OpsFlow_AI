"""Immutable contracts shared by the orchestration transport and application seam."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import OrderState, SourceDocumentType


class IntakeExecution(Enum):
    """Whether an intake execution completed or stood down safely."""

    COMPLETED = "COMPLETED"
    STANDING_DOWN = "STANDING_DOWN"


@dataclass(frozen=True, slots=True)
class OrchestrationIntakeCommand:
    """Current-request document bytes and source identity for orchestration."""

    content: bytes
    document_type: SourceDocumentType
    filename: str
    mime_type: str
    message_id: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OrchestrationIntakeResult:
    """Narrow result returned by the future orchestration application service."""

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    idempotent_replay: bool
    execution: IntakeExecution


class OrchestrationIntakeHandler(Protocol):
    """Application seam owned by the future orchestration implementation."""

    async def __call__(
        self,
        session: AsyncSession,
        command: OrchestrationIntakeCommand,
        actor: str,
        recorded_at: datetime,
    ) -> OrchestrationIntakeResult: ...
