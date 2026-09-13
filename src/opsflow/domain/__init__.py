"""Pure standard-library supporting domain records."""

from .errors import DomainValidationError, InvalidStateTransitionError
from .order import Order, OrderState
from .records import (
    AuditEvent,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)

__all__ = [
    "AuditEvent",
    "DomainValidationError",
    "InvalidStateTransitionError",
    "Order",
    "OrderLine",
    "OrderState",
    "SourceDocument",
    "SourceDocumentType",
    "ValidationIssue",
    "ValidationSeverity",
]
