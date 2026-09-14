"""Application errors independent of transport concerns."""

from uuid import UUID


class OrderNotFoundError(Exception):
    """Raised when a requested order does not exist."""

    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        super().__init__(f"Order {order_id} was not found.")
