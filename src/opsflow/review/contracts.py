"""Immutable, infrastructure-independent human review value contracts."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from opsflow.domain.errors import DomainValidationError


class OperatorRole(Enum):
    """The fixed operator roles recognized by Phase 6."""

    REVIEWER = "REVIEWER"
    APPROVER = "APPROVER"
    ELEVATED_APPROVER = "ELEVATED_APPROVER"


def _require_actor(actor: object) -> None:
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise DomainValidationError("actor must be nonblank and at most 128 characters")


def _require_optional_text(name: str, value: object) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DomainValidationError(f"{name} must be a nonblank string or None")


def _require_optional_date(name: str, value: object) -> None:
    if value is not None and type(value) is not date:
        raise DomainValidationError(f"{name} must be a date or None")


def _require_optional_decimal(name: str, value: object) -> None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
        raise DomainValidationError(f"{name} must be a finite Decimal or None")


@dataclass(frozen=True, slots=True)
class OperatorContext:
    """Server-resolved identity and role for one application operation."""

    actor: str
    role: OperatorRole

    def __post_init__(self) -> None:
        _require_actor(self.actor)
        if not isinstance(self.role, OperatorRole):
            raise DomainValidationError("role must be an OperatorRole")


@dataclass(frozen=True, slots=True)
class ReviewLine:
    """Untrusted editable values for one ordered review line."""

    sku: str | None
    description: str | None
    quantity: Decimal | None
    submitted_price: Decimal | None

    def __post_init__(self) -> None:
        _require_optional_text("sku", self.sku)
        _require_optional_text("description", self.description)
        _require_optional_decimal("quantity", self.quantity)
        _require_optional_decimal("submitted_price", self.submitted_price)


@dataclass(frozen=True, slots=True)
class ReviewDraft:
    """Complete immutable but untrusted business values for human review."""

    customer_name: str | None
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    lines: tuple[ReviewLine, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("customer_name", self.customer_name),
            ("customer_reference", self.customer_reference),
            ("po_number", self.po_number),
            ("currency", self.currency),
        ):
            _require_optional_text(name, value)
        _require_optional_date("order_date", self.order_date)
        _require_optional_date("requested_delivery_date", self.requested_delivery_date)
        if not isinstance(self.lines, tuple) or not all(
            isinstance(line, ReviewLine) for line in self.lines
        ):
            raise DomainValidationError("lines must be a tuple of ReviewLine")


@dataclass(frozen=True, slots=True)
class ReviewChange:
    """One server-computed canonical change from a prior review draft."""

    field_path: str
    old_value: object
    new_value: object


@dataclass(frozen=True, slots=True)
class ReviewRevision:
    """An immutable persisted review-draft revision and its provenance."""

    id: UUID
    order_id: UUID
    extraction_snapshot_id: UUID
    revision_number: int
    payload: ReviewDraft
    changes: tuple[ReviewChange, ...]
    actor: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("id", self.id),
            ("order_id", self.order_id),
            ("extraction_snapshot_id", self.extraction_snapshot_id),
        ):
            if not isinstance(value, UUID):
                raise DomainValidationError(f"{name} must be a UUID")
        if type(self.revision_number) is not int or self.revision_number <= 0:
            raise DomainValidationError("revision_number must be a positive integer")
        if not isinstance(self.payload, ReviewDraft):
            raise DomainValidationError("payload must be a ReviewDraft")
        if not isinstance(self.changes, tuple) or not all(
            isinstance(change, ReviewChange) for change in self.changes
        ):
            raise DomainValidationError("changes must be a tuple of ReviewChange")
        _require_actor(self.actor)
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is None:
            raise DomainValidationError("created_at must be a timezone-aware datetime")
