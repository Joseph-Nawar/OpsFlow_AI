"""Durable ownership checks for one Phase 7 intake execution."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from opsflow.persistence.repositories import PersistedOrder


INTAKE_EXECUTION_BUDGET_SECONDS = 180
INTAKE_OWNERSHIP_LEASE_SECONDS = 210


class StaleIntakeOwnershipError(RuntimeError):
    """The caller no longer owns the current Phase 7 intake fence."""


async def require_current_intake_ownership(
    session: AsyncSession,
    persisted: "PersistedOrder",
    ownership_token: UUID | None,
) -> None:
    """Fail closed unless the supplied fence is current and unexpired.

    The caller must have loaded ``persisted`` with a row lock immediately before
    this check.  ``clock_timestamp()`` is read after that lock is acquired so a
    lock wait cannot make the expiry decision stale within a transaction.
    """

    current_token = persisted.intake_claim_token
    current_expiry = persisted.intake_claim_expires_at
    if current_token is None and ownership_token is None:
        return

    now = await session.scalar(select(func.clock_timestamp()))
    if (
        ownership_token is None
        or current_token != ownership_token
        or current_expiry is None
        or not isinstance(now, datetime)
        or current_expiry <= now
    ):
        raise StaleIntakeOwnershipError("Phase 7 intake ownership is stale or no longer current")


__all__ = [
    "INTAKE_EXECUTION_BUDGET_SECONDS",
    "INTAKE_OWNERSHIP_LEASE_SECONDS",
    "StaleIntakeOwnershipError",
    "require_current_intake_ownership",
]
