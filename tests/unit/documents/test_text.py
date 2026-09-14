from pathlib import Path

import pytest

from opsflow.documents.errors import DocumentParseError
from opsflow.documents.models import DocumentWarning
from opsflow.documents.text import parse_text_document

FIXTURE_ROOT = Path("fixtures/documents/text")


def test_parse_text_decodes_synthetic_plain_text_fixture() -> None:
    content = (FIXTURE_ROOT / "clean-po.txt").read_bytes()

    parsed = parse_text_document(content)

    assert parsed.text == "Purchase Order: PO-1001\nSKU: ABC-1\nQuantity: 10\n"
    assert parsed.pages == ()
    assert parsed.tables == ()
    assert parsed.warnings == ()


def test_parse_text_handles_utf8_bom_and_nfc() -> None:
    content = (FIXTURE_ROOT / "bom-nfc.txt").read_bytes()

    parsed = parse_text_document(content)

    assert parsed.text == "Café\nRésumé\n"


def test_parse_text_normalizes_line_endings_without_stripping_whitespace() -> None:
    parsed = parse_text_document(b"  first\r\nsecond\r  ")

    assert parsed.text == "  first\nsecond\n  "


def test_parse_text_empty_content_returns_exact_empty_text_warning() -> None:
    parsed = parse_text_document(b" \t\r\n")

    assert parsed.text == " \t\n"
    assert parsed.warnings == (
        DocumentWarning(
            code="EMPTY_TEXT",
            message="Document contains no non-whitespace text.",
        ),
    )
    assert parsed.pages == ()
    assert parsed.tables == ()


def test_parse_text_rejects_invalid_utf8_without_echoing_content() -> None:
    with pytest.raises(DocumentParseError, match="UTF-8") as raised:
        parse_text_document(b"private-document-body\xff")

    assert "private-document-body" not in str(raised.value)


def test_parse_text_treats_email_headers_and_attachment_text_as_plain_text() -> None:
    content = b"From: sender@example.test\r\nSubject: Order\r\n\r\nAttachment: none"

    parsed = parse_text_document(content)

    assert parsed.text == ("From: sender@example.test\nSubject: Order\n\nAttachment: none")
    assert parsed.pages == ()
    assert parsed.tables == ()
