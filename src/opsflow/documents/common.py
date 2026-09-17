"""Shared deterministic helpers for Phase 3 document parsers."""

import hashlib
import json
import re
import unicodedata

from opsflow.documents.errors import DocumentParseError, DocumentValidationError
from opsflow.documents.models import CanonicalTable

_MIME_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")


def normalize_text(value: str) -> str:
    """Apply conservative line-ending and Unicode normalization."""
    if not isinstance(value, str):
        raise DocumentValidationError("text value must be a string")
    line_normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", line_normalized)


def _split_mime_components(value: str) -> list[str]:
    components: list[str] = []
    current: list[str] = []
    in_quotes = False
    escaped = False

    for character in value:
        if in_quotes:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_quotes = False
        elif character == '"':
            in_quotes = True
        elif character == ";":
            components.append("".join(current))
            current = []
            continue
        current.append(character)

    if in_quotes or escaped:
        raise DocumentValidationError("MIME declaration contains an invalid parameter")
    components.append("".join(current))
    return components


def _validate_mime_parameter(parameter: str) -> None:
    if "=" not in parameter:
        raise DocumentValidationError("MIME declaration contains an invalid parameter")
    name, value = parameter.split("=", 1)
    name = name.strip()
    value = value.strip()
    if not _MIME_TOKEN.fullmatch(name) or not value:
        raise DocumentValidationError("MIME declaration contains an invalid parameter")

    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            raise DocumentValidationError("MIME declaration contains an invalid parameter")
        escaped = False
        for character in value[1:-1]:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                raise DocumentValidationError("MIME declaration contains an invalid parameter")
        if escaped:
            raise DocumentValidationError("MIME declaration contains an invalid parameter")
    elif not _MIME_TOKEN.fullmatch(value):
        raise DocumentValidationError("MIME declaration contains an invalid parameter")


def normalize_mime_type(declared: str) -> str:
    """Validate and return the lowercase base media type."""
    if not isinstance(declared, str):
        raise DocumentValidationError("MIME type declaration must be a string")
    stripped = declared.strip()
    if not stripped:
        raise DocumentValidationError("MIME type declaration must not be blank")

    components = _split_mime_components(stripped)
    base = components[0].strip()
    if base.count("/") != 1:
        raise DocumentValidationError("MIME type declaration has an invalid base type")
    media_type, subtype = base.split("/", 1)
    if not _MIME_TOKEN.fullmatch(media_type) or not _MIME_TOKEN.fullmatch(subtype):
        raise DocumentValidationError("MIME type declaration has an invalid base type")
    for parameter in components[1:]:
        _validate_mime_parameter(parameter.strip())
    return f"{media_type.lower()}/{subtype.lower()}"


def decode_utf8(content: bytes) -> str:
    """Decode UTF-8 content, removing one UTF-8 BOM when present."""
    if not isinstance(content, bytes):
        raise DocumentValidationError("UTF-8 content must be bytes")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("document content is not valid UTF-8") from exc


def sha256_bytes(content: bytes) -> str:
    """Return the SHA-256 digest of the exact supplied bytes."""
    if not isinstance(content, bytes):
        raise DocumentValidationError("hash input must be bytes")
    return hashlib.sha256(content).hexdigest()


def render_table_text(table: CanonicalTable) -> str:
    """Render one table as a stable heading followed by compact JSON rows."""
    if not isinstance(table, CanonicalTable):
        raise DocumentValidationError("table value must be a CanonicalTable")
    rows = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in table.rows]
    return "\n".join((f"# {table.name}", *rows))


def render_tables_text(tables: tuple[CanonicalTable, ...]) -> str:
    """Render ordered tables separated by one blank line."""
    if not isinstance(tables, tuple) or any(
        not isinstance(table, CanonicalTable) for table in tables
    ):
        raise DocumentValidationError("tables value must be a tuple of CanonicalTable")
    return "\n\n".join(render_table_text(table) for table in tables)
