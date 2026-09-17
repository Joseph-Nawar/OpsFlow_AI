"""Strict provider transport models and immutable extraction records."""

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

from opsflow.domain.records import SourceDocumentType


def _reject_blank_optional(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("blank strings must be represented as null")
    return value


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("blank strings are not valid evidence values")
    return value


class ProviderLineResponse(BaseModel):
    """Strict JSON-safe response fields for one extracted line."""

    model_config = ConfigDict(extra="forbid")

    sku: StrictStr | None
    description: StrictStr | None
    quantity: StrictStr | None
    submitted_price: StrictStr | None

    _reject_blank_scalars = field_validator("sku", "description", "quantity", "submitted_price")(
        _reject_blank_optional
    )


class ProviderEvidenceResponse(BaseModel):
    """Strict JSON-safe provider evidence record."""

    model_config = ConfigDict(extra="forbid")

    field_path: StrictStr
    source_location: StrictStr
    quote: StrictStr

    _reject_blank_values = field_validator("field_path", "source_location", "quote")(_reject_blank)


class ProviderExtractionResponse(BaseModel):
    """Strict JSON-safe structured provider response."""

    model_config = ConfigDict(extra="forbid")

    customer_name: StrictStr | None
    customer_reference: StrictStr | None
    po_number: StrictStr | None
    order_date: StrictStr | None
    requested_delivery_date: StrictStr | None
    currency: StrictStr | None
    lines: list[ProviderLineResponse]
    notes: StrictStr | None
    evidence: list[ProviderEvidenceResponse]

    _reject_blank_scalars = field_validator(
        "customer_name",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "notes",
    )(_reject_blank_optional)


def build_provider_response_schema() -> dict[str, object]:
    """Return a detached JSON-safe schema for provider structured output."""

    return deepcopy(ProviderExtractionResponse.model_json_schema())


def _require_optional_string(name: str, value: object) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or None")


def _require_finite_decimal(name: str, value: object) -> None:
    if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
        raise ValueError(f"{name} must be a finite Decimal or None")


def _require_optional_date(name: str, value: object) -> None:
    if value is not None and type(value) is not date:
        raise ValueError(f"{name} must be a date or None")


@dataclass(frozen=True, slots=True)
class ExtractedLine:
    """Immutable interpreted line data without business-line invariants."""

    sku: str | None
    description: str | None
    quantity: Decimal | None
    submitted_price: Decimal | None

    def __post_init__(self) -> None:
        _require_optional_string("sku", self.sku)
        _require_optional_string("description", self.description)
        _require_finite_decimal("quantity", self.quantity)
        _require_finite_decimal("submitted_price", self.submitted_price)


@dataclass(frozen=True, slots=True)
class Evidence:
    """One provider evidence claim after deterministic grounding."""

    field_path: str
    source_location: str
    quote: str

    def __post_init__(self) -> None:
        for name, value in (
            ("field_path", self.field_path),
            ("source_location", self.source_location),
            ("quote", self.quote),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonblank string")


@dataclass(frozen=True, slots=True)
class ExtractionDraft:
    """Immutable typed extraction data tied to one canonical source."""

    source_sha256: str
    source_document_type: SourceDocumentType
    customer_name: str | None
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    lines: tuple[ExtractedLine, ...]
    notes: str | None
    evidence: tuple[Evidence, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
        ):
            raise ValueError("source_sha256 must be a lowercase SHA-256 hex digest")
        if not isinstance(self.source_document_type, SourceDocumentType):
            raise ValueError("source_document_type must be a SourceDocumentType")
        for name, value in (
            ("customer_name", self.customer_name),
            ("customer_reference", self.customer_reference),
            ("po_number", self.po_number),
            ("currency", self.currency),
            ("notes", self.notes),
        ):
            _require_optional_string(name, value)
        _require_optional_date("order_date", self.order_date)
        _require_optional_date("requested_delivery_date", self.requested_delivery_date)
        if not isinstance(self.lines, tuple) or not all(
            isinstance(line, ExtractedLine) for line in self.lines
        ):
            raise ValueError("lines must be a tuple of ExtractedLine")
        if not isinstance(self.evidence, tuple) or not all(
            isinstance(item, Evidence) for item in self.evidence
        ):
            raise ValueError("evidence must be a tuple of Evidence")


__all__ = [
    "Evidence",
    "ExtractedLine",
    "ExtractionDraft",
    "ProviderEvidenceResponse",
    "ProviderExtractionResponse",
    "ProviderLineResponse",
    "build_provider_response_schema",
]
