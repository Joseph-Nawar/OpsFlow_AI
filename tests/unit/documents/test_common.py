import pytest

from opsflow.documents.common import (
    decode_utf8,
    normalize_mime_type,
    normalize_text,
    render_table_text,
    render_tables_text,
    sha256_bytes,
)
from opsflow.documents.errors import DocumentParseError, DocumentValidationError
from opsflow.documents.models import CanonicalTable


def test_normalize_text_preserves_whitespace_and_normalizes_line_endings() -> None:
    value = "  A\r\nB\r\n\rC  "

    assert normalize_text(value) == "  A\nB\n\nC  "


def test_normalize_text_applies_unicode_nfc_without_lowercasing() -> None:
    assert normalize_text("Cafe\u0301\rOrder") == "Café\nOrder"
    assert normalize_text("SKU ABC") == "SKU ABC"


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        (" text/plain ", "text/plain"),
        ("TEXT/PLAIN; charset=utf-8", "text/plain"),
        ('text/plain; note="a;b"', "text/plain"),
    ],
)
def test_normalize_mime_type_returns_lowercase_base_type(declared: str, expected: str) -> None:
    assert normalize_mime_type(declared) == expected


@pytest.mark.parametrize(
    "declared",
    [
        "",
        "   ",
        "text",
        "/plain",
        "text/",
        "text/ plain",
        "text /plain",
        "text / plain",
        "text/\tplain",
        "text\t/plain",
        "text/plain; charset",
        "text/plain; =utf-8",
        "text/plain; charset=",
        'text/plain; note="unterminated',
    ],
)
def test_normalize_mime_type_rejects_blank_or_malformed_declarations(
    declared: str,
) -> None:
    with pytest.raises(DocumentValidationError, match="MIME"):
        normalize_mime_type(declared)


def test_decode_utf8_accepts_bom_and_plain_utf8() -> None:
    assert decode_utf8(b"plain text") == "plain text"
    assert decode_utf8("\ufeffBOM text".encode("utf-8")) == "BOM text"


def test_decode_utf8_rejects_invalid_bytes_without_echoing_content() -> None:
    secret = b"private-document-body\xff"

    with pytest.raises(DocumentParseError) as raised:
        decode_utf8(secret)

    assert "private-document-body" not in str(raised.value)


def test_sha256_bytes_hashes_exact_original_bytes() -> None:
    content = b"A\r\nB"

    assert sha256_bytes(content) == (
        "255e24970eef1cf6a0503f246be4b2ecd25d69bbbeb4073f4abb26d62886f64b"
    )
    assert sha256_bytes(content) != sha256_bytes(b"A\nB")


def test_render_table_text_uses_compact_unicode_json_rows() -> None:
    table = CanonicalTable(
        name="CSV",
        rows=(("SKU", "Description"), ("ABC-1", 'café, "special"')),
    )

    assert render_table_text(table) == (
        '# CSV\n["SKU","Description"]\n["ABC-1","café, \\"special\\""]'
    )


def test_render_tables_text_preserves_table_order_and_ragged_rows() -> None:
    tables = (
        CanonicalTable(name="First", rows=(("A", "B"), ("1",))),
        CanonicalTable(name="Second", rows=()),
    )

    assert render_tables_text(tables) == '# First\n["A","B"]\n["1"]\n\n# Second'
