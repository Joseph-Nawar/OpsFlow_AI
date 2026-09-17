"""Strict provider-response conversion and deterministic evidence grounding."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from opsflow.documents.models import CanonicalDocument
from opsflow.extraction.errors import ExtractionResponseError
from opsflow.extraction.models import (
    Evidence,
    ExtractedLine,
    ExtractionDraft,
    ProviderExtractionResponse,
)
from opsflow.extraction.prompt import RenderedSource

_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_DECIMAL_PATTERN = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_LINE_FIELD_PATTERN = re.compile(
    r"^lines\[(0|[1-9][0-9]*)\]\.(sku|description|quantity|submitted_price)$"
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "customer_name",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "notes",
    }
)


def parse_provider_response(payload: object) -> ProviderExtractionResponse:
    """Validate one provider payload without exposing its contents in errors."""

    try:
        return ProviderExtractionResponse.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise ExtractionResponseError("provider response failed strict schema validation") from exc


def parse_iso_date(value: str | None, *, field_path: str) -> date | None:
    """Convert one exact ISO calendar string without locale or policy inference."""

    if value is None:
        return None
    if not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None:
        raise ExtractionResponseError(f"invalid ISO date for {field_path}")

    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError as exc:
        raise ExtractionResponseError(f"invalid ISO date for {field_path}") from exc


def parse_decimal_text(value: str | None, *, field_path: str) -> Decimal | None:
    """Convert one exact finite ASCII decimal string without business policy."""

    if value is None:
        return None
    if not isinstance(value, str) or _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ExtractionResponseError(f"invalid decimal for {field_path}")

    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ExtractionResponseError(f"invalid decimal for {field_path}") from exc
    if not parsed.is_finite():
        raise ExtractionResponseError(f"invalid decimal for {field_path}")
    return parsed


def _resolve_evidence_value(
    response: ProviderExtractionResponse,
    field_path: str,
) -> object:
    if field_path in _TOP_LEVEL_FIELDS:
        return getattr(response, field_path)

    match = _LINE_FIELD_PATTERN.fullmatch(field_path)
    if match is None:
        raise ExtractionResponseError("invalid evidence field path")

    line_index = int(match.group(1))
    if line_index >= len(response.lines):
        raise ExtractionResponseError(f"evidence line index is out of range: {field_path}")
    return getattr(response.lines[line_index], match.group(2))


def validate_evidence(
    response: ProviderExtractionResponse,
    rendered_source: RenderedSource,
) -> tuple[Evidence, ...]:
    """Verify every provider evidence claim against exact response/source values."""

    segments_by_location = {segment.location: segment for segment in rendered_source.segments}
    seen_paths: set[str] = set()
    grounded: list[Evidence] = []

    for item in response.evidence:
        field_path = item.field_path
        if field_path in seen_paths:
            raise ExtractionResponseError(f"duplicate evidence field path: {field_path}")
        seen_paths.add(field_path)

        value = _resolve_evidence_value(response, field_path)
        if value is None:
            raise ExtractionResponseError(f"evidence refers to null field: {field_path}")

        segment = segments_by_location.get(item.source_location)
        if segment is None:
            raise ExtractionResponseError(
                f"evidence source location does not exist: {item.source_location}"
            )
        if not isinstance(item.quote, str) or not item.quote:
            raise ExtractionResponseError("evidence quote must be non-empty")
        if item.quote not in segment.text:
            raise ExtractionResponseError("evidence quote is not grounded in its source segment")

        grounded.append(
            Evidence(
                field_path=field_path,
                source_location=item.source_location,
                quote=item.quote,
            )
        )

    return tuple(grounded)


def convert_provider_response(
    response: ProviderExtractionResponse,
    document: CanonicalDocument,
    rendered_source: RenderedSource,
) -> ExtractionDraft:
    """Convert a validated provider response into one immutable typed draft."""

    lines = tuple(
        ExtractedLine(
            sku=line.sku,
            description=line.description,
            quantity=parse_decimal_text(
                line.quantity,
                field_path=f"lines[{line_index}].quantity",
            ),
            submitted_price=parse_decimal_text(
                line.submitted_price,
                field_path=f"lines[{line_index}].submitted_price",
            ),
        )
        for line_index, line in enumerate(response.lines)
    )
    evidence = validate_evidence(response, rendered_source)

    return ExtractionDraft(
        source_sha256=document.sha256,
        source_document_type=document.document_type,
        customer_name=response.customer_name,
        customer_reference=response.customer_reference,
        po_number=response.po_number,
        order_date=parse_iso_date(response.order_date, field_path="order_date"),
        requested_delivery_date=parse_iso_date(
            response.requested_delivery_date,
            field_path="requested_delivery_date",
        ),
        currency=response.currency,
        lines=lines,
        notes=response.notes,
        evidence=evidence,
    )


__all__ = [
    "convert_provider_response",
    "parse_decimal_text",
    "parse_iso_date",
    "parse_provider_response",
    "validate_evidence",
]
