"""Immutable supporting records for the OpsFlow domain."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from .errors import DomainValidationError


class SourceDocumentType(Enum):
    EMAIL_BODY = "EMAIL_BODY"
    PDF = "PDF"
    XLSX = "XLSX"
    CSV = "CSV"
    FORM = "FORM"


class ValidationSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


def _require_non_blank(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field_name} must be a non-blank string")


def _require_decimal(value: object, field_name: str, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainValidationError(f"{field_name} must be a finite Decimal")
    if positive and value <= 0:
        raise DomainValidationError(f"{field_name} must be greater than zero")
    if not positive and value < 0:
        raise DomainValidationError(f"{field_name} must be greater than or equal to zero")


@dataclass(frozen=True, slots=True)
class OrderLine:
    id: UUID
    sku: str | None
    description: str | None
    quantity: Decimal
    submitted_price: Decimal | None
    trusted_catalogue_price: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("id must be a UUID")
        if self.sku is not None and not isinstance(self.sku, str):
            raise DomainValidationError("sku must be a string or None")
        if self.description is not None and not isinstance(self.description, str):
            raise DomainValidationError("description must be a string or None")
        _require_decimal(self.quantity, "quantity", positive=True)
        if self.submitted_price is not None:
            _require_decimal(self.submitted_price, "submitted_price")
        if self.trusted_catalogue_price is not None:
            _require_decimal(self.trusted_catalogue_price, "trusted_catalogue_price")
        if not (
            (self.sku is not None and self.sku.strip())
            or (self.description is not None and self.description.strip())
        ):
            raise DomainValidationError("sku or description must be non-blank")


@dataclass(frozen=True, slots=True)
class SourceDocument:
    id: UUID
    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None
    storage_reference: str | None
    metadata: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("id must be a UUID")
        if not isinstance(self.document_type, SourceDocumentType):
            raise DomainValidationError("document_type must be a SourceDocumentType")
        _require_non_blank(self.name, "name")
        _require_non_blank(self.mime_type, "mime_type")
        if not isinstance(self.sha256, str) or not re.fullmatch(
            r"[0-9A-Fa-f]{64}", self.sha256, flags=re.ASCII
        ):
            raise DomainValidationError("sha256 must be 64 ASCII hexadecimal characters")
        if self.message_id is not None and not isinstance(self.message_id, str):
            raise DomainValidationError("message_id must be a string or None")
        if self.storage_reference is not None and not isinstance(self.storage_reference, str):
            raise DomainValidationError("storage_reference must be a string or None")
        if not isinstance(self.metadata, tuple):
            raise DomainValidationError("metadata must be a tuple of string pairs")
        for pair in self.metadata:
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or not all(isinstance(value, str) for value in pair)
            ):
                raise DomainValidationError("metadata must contain only (str, str) pairs")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    rule_code: str
    severity: ValidationSeverity
    field: str | None
    expected: object | None
    actual: object | None
    explanation: str

    def __post_init__(self) -> None:
        _require_non_blank(self.rule_code, "rule_code")
        if not isinstance(self.severity, ValidationSeverity):
            raise DomainValidationError("severity must be a ValidationSeverity")
        if self.field is not None:
            _require_non_blank(self.field, "field")
        _require_non_blank(self.explanation, "explanation")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    order_id: UUID
    event_type: str
    actor: str
    occurred_at: datetime
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise DomainValidationError("id must be a UUID")
        if not isinstance(self.order_id, UUID):
            raise DomainValidationError("order_id must be a UUID")
        _require_non_blank(self.event_type, "event_type")
        _require_non_blank(self.actor, "actor")
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.utcoffset() is None:
            raise DomainValidationError("occurred_at must be timezone-aware")
        _require_non_blank(self.description, "description")
