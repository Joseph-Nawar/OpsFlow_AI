"""Domain-specific errors for the OpsFlow domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .order import OrderState


class DomainValidationError(ValueError):
    """Raised when a domain record violates a structural invariant."""


class InvalidStateTransitionError(DomainValidationError):
    """Raised when an invalid lifecycle operation is requested."""

    def __init__(
        self,
        current_state: OrderState,
        requested_state: object | None,
        operation: str,
    ) -> None:
        self.current_state = current_state
        self.requested_state = requested_state
        self.operation = operation
        requested = getattr(requested_state, "name", repr(requested_state))
        super().__init__(f"Cannot {operation} from {current_state.name} to {requested}")
