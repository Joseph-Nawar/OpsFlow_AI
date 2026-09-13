"""Immutable Order aggregate and state definitions."""

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from uuid import UUID

from .errors import DomainValidationError
from .records import OrderLine, SourceDocument


class OrderState(Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    SYNCING = "SYNCING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


@dataclass(frozen=True, slots=True)
class Order:
    id: UUID
    customer_reference: str | None = None
    po_number: str | None = None
    order_date: date | None = None
    requested_delivery_date: date | None = None
    currency: str | None = None
    lines: tuple[OrderLine, ...] = ()
    source_documents: tuple[SourceDocument, ...] = ()
    state: OrderState = OrderState.RECEIVED
    failure_origin: OrderState | None = None

    @classmethod
    def received(
        cls,
        id: UUID,
        customer_reference: str | None = None,
        po_number: str | None = None,
        order_date: date | None = None,
        requested_delivery_date: date | None = None,
        currency: str | None = None,
        lines: tuple[OrderLine, ...] = (),
        source_documents: tuple[SourceDocument, ...] = (),
    ) -> "Order":
        return cls(
            id=id,
            customer_reference=customer_reference,
            po_number=po_number,
            order_date=order_date,
            requested_delivery_date=requested_delivery_date,
            currency=currency,
            lines=lines,
            source_documents=source_documents,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("id must be a UUID")
        if self.customer_reference is not None and not isinstance(self.customer_reference, str):
            raise DomainValidationError("customer_reference must be a string or None")
        if self.po_number is not None and not isinstance(self.po_number, str):
            raise DomainValidationError("po_number must be a string or None")
        if self.order_date is not None and type(self.order_date) is not date:
            raise DomainValidationError("order_date must be a date or None")
        if (
            self.requested_delivery_date is not None
            and type(self.requested_delivery_date) is not date
        ):
            raise DomainValidationError("requested_delivery_date must be a date or None")
        if self.currency is not None and (
            not isinstance(self.currency, str)
            or re.fullmatch(r"[A-Z]{3}", self.currency, flags=re.ASCII) is None
        ):
            raise DomainValidationError("currency must be None or three uppercase ASCII letters")
        if not isinstance(self.lines, tuple) or not all(
            isinstance(line, OrderLine) for line in self.lines
        ):
            raise DomainValidationError("lines must be a tuple of OrderLine")
        if not isinstance(self.source_documents, tuple) or not all(
            isinstance(document, SourceDocument) for document in self.source_documents
        ):
            raise DomainValidationError("source_documents must be a tuple of SourceDocument")
        if not isinstance(self.state, OrderState):
            raise DomainValidationError("state must be an OrderState")
        if self.failure_origin is not None and not isinstance(self.failure_origin, OrderState):
            raise DomainValidationError("failure_origin must be an OrderState or None")
        if self.state in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL):
            if self.failure_origin not in (
                OrderState.PROCESSING,
                OrderState.EXTRACTED,
                OrderState.SYNCING,
            ):
                raise DomainValidationError(
                    "failure states require a processing, extracted, or syncing origin"
                )
        elif self.failure_origin is not None:
            raise DomainValidationError("non-failure states must not have a failure origin")
