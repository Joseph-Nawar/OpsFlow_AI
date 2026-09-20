"""Canonical review-draft projection and JSON serialization."""

import re
from datetime import date
from decimal import Decimal

from opsflow.domain import DomainValidationError
from opsflow.extraction.models import ExtractedLine, ExtractionDraft

from .contracts import ReviewChange, ReviewDraft, ReviewLine, ReviewRevision

_DRAFT_KEYS = (
    "customer_name",
    "customer_reference",
    "po_number",
    "order_date",
    "requested_delivery_date",
    "currency",
    "lines",
)
_LINE_KEYS = ("sku", "description", "quantity", "submitted_price")
_SCALAR_CHANGE_PATHS = (
    "customer_name",
    "customer_reference",
    "po_number",
    "order_date",
    "requested_delivery_date",
    "currency",
)
_CHANGE_PATHS = (*_SCALAR_CHANGE_PATHS, "lines")
_DATE_FIELDS = frozenset({"order_date", "requested_delivery_date"})
_TEXT_FIELDS = frozenset({"customer_name", "customer_reference", "po_number", "currency"})
_CANONICAL_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", flags=re.ASCII)
_CANONICAL_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", flags=re.ASCII)


def review_draft_to_payload(draft: ReviewDraft) -> dict[str, object]:
    """Return the exact JSON-safe canonical payload for one complete draft."""

    if not isinstance(draft, ReviewDraft):
        raise DomainValidationError("draft must be a ReviewDraft")
    if type(draft.lines) is not tuple:
        raise DomainValidationError("draft lines must be an immutable tuple")

    lines = [_review_line_to_payload(line) for line in draft.lines]
    return {
        "customer_name": _optional_text_to_payload(draft.customer_name, "customer_name"),
        "customer_reference": _optional_text_to_payload(
            draft.customer_reference, "customer_reference"
        ),
        "po_number": _optional_text_to_payload(draft.po_number, "po_number"),
        "order_date": _optional_date_to_payload(draft.order_date, "order_date"),
        "requested_delivery_date": _optional_date_to_payload(
            draft.requested_delivery_date, "requested_delivery_date"
        ),
        "currency": _optional_text_to_payload(draft.currency, "currency"),
        "lines": lines,
    }


def review_draft_from_payload(payload: object) -> ReviewDraft:
    """Parse only the exact canonical JSON shape into an immutable draft."""

    root = _require_object(payload, "payload")
    _require_exact_keys(root, _DRAFT_KEYS, "payload")
    lines_value = root["lines"]
    if type(lines_value) is not list:
        raise DomainValidationError("payload.lines must be a JSON array")

    try:
        return ReviewDraft(
            customer_name=_optional_text_from_payload(root["customer_name"], "customer_name"),
            customer_reference=_optional_text_from_payload(
                root["customer_reference"], "customer_reference"
            ),
            po_number=_optional_text_from_payload(root["po_number"], "po_number"),
            order_date=_optional_date_from_payload(root["order_date"], "order_date"),
            requested_delivery_date=_optional_date_from_payload(
                root["requested_delivery_date"], "requested_delivery_date"
            ),
            currency=_optional_text_from_payload(root["currency"], "currency"),
            lines=tuple(
                _review_line_from_payload(value, f"lines[{index}]")
                for index, value in enumerate(lines_value)
            ),
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError("payload does not satisfy the ReviewDraft contract") from error


def review_draft_from_extraction(draft: ExtractionDraft) -> ReviewDraft:
    """Project only editable business values from the immutable extraction."""

    if not isinstance(draft, ExtractionDraft):
        raise DomainValidationError("draft must be an ExtractionDraft")
    if type(draft.lines) is not tuple:
        raise DomainValidationError("extraction lines must be an immutable tuple")
    lines: list[ReviewLine] = []
    for line in draft.lines:
        if not isinstance(line, ExtractedLine):
            raise DomainValidationError("extraction lines must contain ExtractedLine values")
        lines.append(ReviewLine(line.sku, line.description, line.quantity, line.submitted_price))
    return ReviewDraft(
        customer_name=draft.customer_name,
        customer_reference=draft.customer_reference,
        po_number=draft.po_number,
        order_date=draft.order_date,
        requested_delivery_date=draft.requested_delivery_date,
        currency=draft.currency,
        lines=tuple(lines),
    )


def compose_extraction_draft(original: ExtractionDraft, candidate: ReviewDraft) -> ExtractionDraft:
    """Combine candidate business values with immutable original provenance."""

    if not isinstance(original, ExtractionDraft):
        raise DomainValidationError("original must be an ExtractionDraft")
    if not isinstance(candidate, ReviewDraft):
        raise DomainValidationError("candidate must be a ReviewDraft")
    return ExtractionDraft(
        source_sha256=original.source_sha256,
        source_document_type=original.source_document_type,
        customer_name=candidate.customer_name,
        customer_reference=candidate.customer_reference,
        po_number=candidate.po_number,
        order_date=candidate.order_date,
        requested_delivery_date=candidate.requested_delivery_date,
        currency=candidate.currency,
        lines=tuple(
            ExtractedLine(
                sku=line.sku,
                description=line.description,
                quantity=line.quantity,
                submitted_price=line.submitted_price,
            )
            for line in candidate.lines
        ),
        notes=original.notes,
        evidence=original.evidence,
    )


def review_changes_to_payload(changes: tuple[ReviewChange, ...]) -> list[dict[str, object]]:
    """Serialize ordered, actual review changes to their exact JSON shape."""

    if type(changes) is not tuple or not all(
        isinstance(change, ReviewChange) for change in changes
    ):
        raise DomainValidationError("changes must be a tuple of ReviewChange")
    result: list[dict[str, object]] = []
    previous_position = -1
    for change in changes:
        if type(change.field_path) is not str or change.field_path not in _CHANGE_PATHS:
            raise DomainValidationError("change field_path is not a canonical review field")
        position = _CHANGE_PATHS.index(change.field_path)
        if position <= previous_position:
            raise DomainValidationError("changes must have unique canonical field order")
        previous_position = position
        old_value = _canonical_change_value(change.field_path, change.old_value)
        new_value = _canonical_change_value(change.field_path, change.new_value)
        if old_value == new_value:
            raise DomainValidationError("review change values must differ")
        result.append(
            {
                "field_path": change.field_path,
                "old_value": old_value,
                "new_value": new_value,
            }
        )
    return result


def review_changes_from_payload(payload: object) -> tuple[ReviewChange, ...]:
    """Strictly parse canonical ordered change entries from a JSON array."""

    if type(payload) is not list:
        raise DomainValidationError("changes must be a JSON array")
    changes: list[ReviewChange] = []
    for index, value in enumerate(payload):
        item = _require_object(value, f"changes[{index}]")
        _require_exact_keys(item, ("field_path", "old_value", "new_value"), f"changes[{index}]")
        field_path = item["field_path"]
        if type(field_path) is not str or field_path not in _CHANGE_PATHS:
            raise DomainValidationError(f"changes[{index}].field_path is not canonical")
        old_value = _canonical_change_value(field_path, item["old_value"])
        new_value = _canonical_change_value(field_path, item["new_value"])
        changes.append(ReviewChange(field_path, old_value, new_value))
    result = tuple(changes)
    review_changes_to_payload(result)
    return result


def compute_review_changes(
    previous: ReviewDraft,
    candidate: ReviewDraft,
) -> tuple[ReviewChange, ...]:
    """Compute scalar differences and at most one ordered-lines change."""

    old_payload = review_draft_to_payload(previous)
    new_payload = review_draft_to_payload(candidate)
    changes: list[ReviewChange] = []
    for field_path in _SCALAR_CHANGE_PATHS:
        old_value = old_payload[field_path]
        new_value = new_payload[field_path]
        if old_value != new_value:
            changes.append(ReviewChange(field_path, old_value, new_value))
    old_lines = old_payload["lines"]
    new_lines = new_payload["lines"]
    if old_lines != new_lines:
        changes.append(ReviewChange("lines", old_lines, new_lines))
    return tuple(changes)


def project_effective_review_draft(
    original: ReviewDraft,
    latest_revision: ReviewRevision | None,
) -> ReviewDraft:
    """Use the original projection or the highest-revision payload supplied."""

    if not isinstance(original, ReviewDraft):
        raise DomainValidationError("original must be a ReviewDraft")
    if latest_revision is None:
        return original
    if not isinstance(latest_revision, ReviewRevision):
        raise DomainValidationError("latest_revision must be a ReviewRevision or None")
    return latest_revision.payload


def _review_line_to_payload(line: ReviewLine) -> dict[str, object]:
    if not isinstance(line, ReviewLine):
        raise DomainValidationError("lines must contain ReviewLine values")
    return {
        "sku": _optional_text_to_payload(line.sku, "sku"),
        "description": _optional_text_to_payload(line.description, "description"),
        "quantity": _optional_decimal_to_payload(line.quantity, "quantity"),
        "submitted_price": _optional_decimal_to_payload(line.submitted_price, "submitted_price"),
    }


def _review_line_from_payload(value: object, field_name: str) -> ReviewLine:
    item = _require_object(value, field_name)
    _require_exact_keys(item, _LINE_KEYS, field_name)
    try:
        return ReviewLine(
            sku=_optional_text_from_payload(item["sku"], f"{field_name}.sku"),
            description=_optional_text_from_payload(
                item["description"], f"{field_name}.description"
            ),
            quantity=_optional_decimal_from_payload(item["quantity"], f"{field_name}.quantity"),
            submitted_price=_optional_decimal_from_payload(
                item["submitted_price"], f"{field_name}.submitted_price"
            ),
        )
    except (TypeError, ValueError) as error:
        raise DomainValidationError(
            f"{field_name} does not satisfy the ReviewLine contract"
        ) from error


def _canonical_change_value(field_path: str, value: object) -> object:
    if field_path == "lines":
        if type(value) is not list:
            raise DomainValidationError("lines change values must be JSON arrays")
        return [
            _review_line_to_payload(_review_line_from_payload(line, f"lines[{index}]"))
            for index, line in enumerate(value)
        ]
    if field_path in _TEXT_FIELDS:
        return _optional_text_from_payload(value, field_path)
    if field_path in _DATE_FIELDS:
        parsed = _optional_date_from_payload(value, field_path)
        return _optional_date_to_payload(parsed, field_path)
    raise DomainValidationError("change field_path is not a canonical review field")


def _optional_text_to_payload(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        raise DomainValidationError(f"{field_name} must be a nonblank string or null")
    return value


def _optional_text_from_payload(value: object, field_name: str) -> str | None:
    return _optional_text_to_payload(value, field_name)


def _optional_date_to_payload(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not date:
        raise DomainValidationError(f"{field_name} must be a date or null")
    return value.isoformat()


def _optional_date_from_payload(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    if type(value) is not str or _CANONICAL_DATE.fullmatch(value) is None:
        raise DomainValidationError(f"{field_name} must be a canonical date string or null")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DomainValidationError(f"{field_name} is not a valid date") from error
    if parsed.isoformat() != value:
        raise DomainValidationError(f"{field_name} is not canonical")
    return parsed


def _optional_decimal_to_payload(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainValidationError(f"{field_name} must be a finite Decimal or null")
    if value == 0:
        return "0"
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return result


def _optional_decimal_from_payload(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not str or _CANONICAL_DECIMAL.fullmatch(value) is None:
        raise DomainValidationError(f"{field_name} must be a canonical Decimal string or null")
    try:
        parsed = Decimal(value)
    except (TypeError, ValueError) as error:
        raise DomainValidationError(f"{field_name} is not a Decimal string") from error
    if not parsed.is_finite() or _optional_decimal_to_payload(parsed, field_name) != value:
        raise DomainValidationError(f"{field_name} is not canonical")
    return parsed


def _require_object(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise DomainValidationError(f"{field_name} must be a JSON object")
    return value


def _require_exact_keys(
    value: dict[str, object], expected: tuple[str, ...], field_name: str
) -> None:
    if set(value) != set(expected):
        raise DomainValidationError(f"{field_name} has an unexpected shape")
