"""Pure standard-library supporting domain records."""

from .errors import DomainValidationError
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
    "OrderLine",
    "SourceDocument",
    "SourceDocumentType",
    "ValidationIssue",
    "ValidationSeverity",
]
