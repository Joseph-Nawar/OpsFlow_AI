from dataclasses import replace
from pathlib import Path

import pytest

from opsflow.documents.csv import parse_csv_document
from opsflow.documents.errors import DocumentLimitError, DocumentParseError
from opsflow.documents.limits import DEFAULT_DOCUMENT_LIMITS
from opsflow.documents.models import CanonicalTable

FIXTURE_ROOT = Path("fixtures/documents/csv")


def test_parse_csv_supports_quoted_delimiters_and_multiline_cells() -> None:
    content = (FIXTURE_ROOT / "quoted-multiline.csv").read_bytes()

    parsed = parse_csv_document(content, DEFAULT_DOCUMENT_LIMITS)

    assert parsed.tables[0].name == "CSV"
    assert parsed.tables[0].rows == (
        ("SKU", "Description", "Quantity"),
        ("ABC-1", "Widget, large\nblue", "10"),
    )
    assert parsed.text == (
        '# CSV\n["SKU","Description","Quantity"]\n["ABC-1","Widget, large\\nblue","10"]'
    )
    assert parsed.pages == ()
    assert parsed.warnings == ()


def test_parse_csv_preserves_empty_cells_and_ragged_records() -> None:
    content = (FIXTURE_ROOT / "empty-cells.csv").read_bytes()

    parsed = parse_csv_document(content, DEFAULT_DOCUMENT_LIMITS)

    assert parsed.tables[0].rows == (
        ("SKU", "Description", "Quantity"),
        ("ABC-1", "", "10"),
        ("", "Blank SKU", ""),
        ("RAGGED",),
    )


def test_parse_csv_preserves_row_and_column_order_without_padding() -> None:
    parsed = parse_csv_document(b"B,A\n2,1\n3", DEFAULT_DOCUMENT_LIMITS)

    assert parsed.tables[0].rows == (("B", "A"), ("2", "1"), ("3",))
    assert parsed.text == '# CSV\n["B","A"]\n["2","1"]\n["3"]'


def test_parse_csv_handles_utf8_bom_nfc_and_line_endings() -> None:
    content = "\ufeffCafe\u0301,Re\u0301sume\u0301\r\n1,2".encode("utf-8")

    parsed = parse_csv_document(content, DEFAULT_DOCUMENT_LIMITS)

    assert parsed.tables[0].rows == (("Café", "Résumé"), ("1", "2"))


def test_parse_csv_preserves_escaped_quotes() -> None:
    parsed = parse_csv_document(
        b'"SKU","Description"\n"A-1","A ""special"" item"',
        DEFAULT_DOCUMENT_LIMITS,
    )

    assert parsed.tables[0].rows == (
        ("SKU", "Description"),
        ("A-1", 'A "special" item'),
    )


def test_parse_csv_zero_records_returns_empty_table_without_warning() -> None:
    parsed = parse_csv_document(b"", DEFAULT_DOCUMENT_LIMITS)

    assert parsed.tables == (CanonicalTable(name="CSV", rows=()),)
    assert parsed.text == "# CSV"
    assert parsed.pages == ()
    assert parsed.warnings == ()


def test_parse_csv_counts_every_record_toward_row_limit() -> None:
    limits = replace(DEFAULT_DOCUMENT_LIMITS, max_csv_rows=2)

    with pytest.raises(DocumentLimitError, match="CSV row limit"):
        parse_csv_document(b"A\nB\nC", limits)


def test_parse_csv_applies_width_limit_to_each_record() -> None:
    limits = replace(DEFAULT_DOCUMENT_LIMITS, max_table_columns=2)

    with pytest.raises(DocumentLimitError, match="table column limit"):
        parse_csv_document(b"A,B\n1,2,3", limits)


def test_parse_csv_rejects_malformed_quoted_input_safely() -> None:
    with pytest.raises(DocumentParseError, match="CSV") as raised:
        parse_csv_document(b'"unterminated', DEFAULT_DOCUMENT_LIMITS)

    assert "unterminated" not in str(raised.value)


def test_parse_csv_is_deterministic_across_repeated_parsing() -> None:
    content = b"A,B\n1,2\n3,4"

    assert parse_csv_document(content, DEFAULT_DOCUMENT_LIMITS) == parse_csv_document(
        content, DEFAULT_DOCUMENT_LIMITS
    )
