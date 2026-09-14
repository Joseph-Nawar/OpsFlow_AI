"""Deterministic standard-library CSV parser for Phase 3."""

import csv as csv_module
import io

from opsflow.documents.common import decode_utf8, normalize_text, render_table_text
from opsflow.documents.errors import DocumentLimitError, DocumentParseError
from opsflow.documents.limits import DocumentLimits
from opsflow.documents.models import CanonicalTable, _ParsedDocumentContent


def parse_csv_document(
    content: bytes,
    limits: DocumentLimits,
) -> _ParsedDocumentContent:
    """Parse UTF-8 CSV into one ordered, possibly ragged canonical table."""
    text = normalize_text(decode_utf8(content))
    reader = csv_module.reader(
        io.StringIO(text, newline=""),
        delimiter=",",
        quotechar='"',
        strict=True,
    )
    rows: list[tuple[str, ...]] = []

    try:
        for row_number, row in enumerate(reader, start=1):
            if row_number > limits.max_csv_rows:
                raise DocumentLimitError("CSV row limit exceeded")
            if len(row) > limits.max_table_columns:
                raise DocumentLimitError("table column limit exceeded")
            rows.append(tuple(normalize_text(cell) for cell in row))
    except DocumentLimitError:
        raise
    except csv_module.Error as exc:
        raise DocumentParseError("CSV content is malformed") from exc

    table = CanonicalTable(name="CSV", rows=tuple(rows))
    return _ParsedDocumentContent(text=render_table_text(table), tables=(table,))
