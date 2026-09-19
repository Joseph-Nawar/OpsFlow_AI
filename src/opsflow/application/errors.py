"""Application errors independent of transport concerns."""

from uuid import UUID

from opsflow.domain import OrderState


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


class SourceDocumentNotFoundError(Exception):
    """Raised when a requested source document does not exist."""

    def __init__(self, source_document_id: UUID) -> None:
        self.source_document_id = source_document_id
        super().__init__("Source document was not found.")


class SourceOwnershipError(Exception):
    """Raised when a source document belongs to another order."""

    def __init__(self, order_id: UUID, source_document_id: UUID) -> None:
        self.order_id = order_id
        self.source_document_id = source_document_id
        super().__init__("Source document does not belong to the requested order.")


class SourceIdentityMismatchError(Exception):
    """Raised when the draft does not match its source document envelope."""

    def __init__(self, order_id: UUID, source_document_id: UUID) -> None:
        self.order_id = order_id
        self.source_document_id = source_document_id
        super().__init__("Source document identity does not match the extraction draft.")


class OrderValidationStateError(Exception):
    """Raised when validation is requested for an ineligible order state."""

    def __init__(self, order_id: UUID, current_state: OrderState) -> None:
        self.order_id = order_id
        self.current_state = current_state
        super().__init__("Order is not in the EXTRACTED validation state.")


class SnapshotReplayError(Exception):
    """Raised when an identical snapshot already exists for the source."""

    def __init__(self, order_id: UUID, source_document_id: UUID) -> None:
        self.order_id = order_id
        self.source_document_id = source_document_id
        super().__init__(
            "An identical extraction snapshot already exists for this order and source."
        )


class SnapshotConflictError(Exception):
    """Raised when a different snapshot already exists for the source."""

    def __init__(self, order_id: UUID, source_document_id: UUID) -> None:
        self.order_id = order_id
        self.source_document_id = source_document_id
        super().__init__(
            "A conflicting extraction snapshot already exists for this order and source."
        )


class ValidationFactsChangedError(Exception):
    """Raised when local validation facts changed before commit."""

    def __init__(self, order_id: UUID) -> None:
        self.order_id = order_id
        super().__init__("Validation facts changed before the operation could commit.")


class InvalidTrustedDataError(Exception):
    """Raised when trusted business data violates its contract."""

    def __init__(self) -> None:
        super().__init__("Trusted business data failed contract validation.")


class BusinessDataProviderError(Exception):
    """Raised when the trusted business-data provider cannot complete safely."""

    def __init__(self) -> None:
        super().__init__("Business data provider operation failed.")
