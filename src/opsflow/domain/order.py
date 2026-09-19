"""Immutable Order aggregate and state definitions."""

import re
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING
from uuid import UUID

from .errors import DomainValidationError, InvalidStateTransitionError
from .records import OrderLine, SourceDocument

if TYPE_CHECKING:
    from opsflow.validation import ValidatedOrderData


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


_NORMAL_TRANSITIONS = MappingProxyType(
    {
        OrderState.RECEIVED: frozenset({OrderState.PROCESSING}),
        OrderState.PROCESSING: frozenset(
            {
                OrderState.EXTRACTED,
                OrderState.FAILED_RETRYABLE,
                OrderState.FAILED_FINAL,
            }
        ),
        OrderState.EXTRACTED: frozenset(
            {
                OrderState.VALIDATED,
                OrderState.FAILED_RETRYABLE,
                OrderState.FAILED_FINAL,
            }
        ),
        OrderState.VALIDATED: frozenset({OrderState.NEEDS_REVIEW, OrderState.READY_FOR_APPROVAL}),
        OrderState.NEEDS_REVIEW: frozenset({OrderState.VALIDATED, OrderState.REJECTED}),
        OrderState.READY_FOR_APPROVAL: frozenset({OrderState.APPROVED, OrderState.REJECTED}),
        OrderState.APPROVED: frozenset({OrderState.SYNCING}),
        OrderState.SYNCING: frozenset(
            {
                OrderState.COMPLETED,
                OrderState.FAILED_RETRYABLE,
                OrderState.FAILED_FINAL,
            }
        ),
        OrderState.COMPLETED: frozenset(),
        OrderState.REJECTED: frozenset(),
        OrderState.FAILED_RETRYABLE: frozenset(),
        OrderState.FAILED_FINAL: frozenset(),
    }
)


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

    def transition_to(self, target: OrderState) -> "Order":
        if not isinstance(target, OrderState) or target not in _NORMAL_TRANSITIONS[self.state]:
            raise InvalidStateTransitionError(self.state, target, "transition_to")

        failure_origin = (
            self.state if target in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL) else None
        )
        return replace(self, state=target, failure_origin=failure_origin)

    def retry(self) -> "Order":
        if self.state is not OrderState.FAILED_RETRYABLE or self.failure_origin is None:
            raise InvalidStateTransitionError(self.state, None, "retry")
        return replace(self, state=self.failure_origin, failure_origin=None)

    def reopen(self) -> "Order":
        if self.state is not OrderState.REJECTED:
            raise InvalidStateTransitionError(self.state, None, "reopen")
        return replace(self, state=OrderState.NEEDS_REVIEW, failure_origin=None)

    def promote_validated_data(
        self,
        data: "ValidatedOrderData",
        line_ids: tuple[UUID, ...],
    ) -> "Order":
        """Return a trusted order snapshot without changing lifecycle state."""

        if self.state is not OrderState.EXTRACTED:
            raise InvalidStateTransitionError(self.state, None, "promote_validated_data")

        from opsflow.validation import ValidatedOrderData

        if not isinstance(data, ValidatedOrderData):
            raise DomainValidationError("data must be a ValidatedOrderData")
        if type(line_ids) is not tuple:
            raise DomainValidationError("line_ids must be an immutable tuple")
        if len(line_ids) != len(data.lines):
            raise DomainValidationError("line_ids must match the validated line count")
        if not all(isinstance(line_id, UUID) for line_id in line_ids):
            raise DomainValidationError("line_ids must contain UUID values")

        lines = tuple(
            OrderLine(
                id=line_id,
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                submitted_price=line.submitted_price,
                trusted_catalogue_price=line.trusted_catalogue_price,
            )
            for line_id, line in zip(line_ids, data.lines, strict=True)
        )
        return Order(
            id=self.id,
            customer_reference=data.customer_reference,
            po_number=data.po_number,
            order_date=data.order_date,
            requested_delivery_date=data.requested_delivery_date,
            currency=data.currency,
            lines=lines,
            source_documents=self.source_documents,
            state=self.state,
            failure_origin=self.failure_origin,
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
