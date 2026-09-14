"""Application errors independent of transport concerns."""

from uuid import UUID


class OrderNotFoundError(Exception):
    """Raised when a requested order does not exist."""

    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        super().__init__(f"Order {order_id} was not found.")


class IdempotencyConflictError(Exception):
    """Raised when a key is reused for a different semantic request."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(
            f"Idempotency key was already used for a different request: {idempotency_key}"
        )
