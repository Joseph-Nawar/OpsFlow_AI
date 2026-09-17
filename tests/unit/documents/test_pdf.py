"""Behavioral tests for the Phase 3 PDF parser."""

import io
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfWriter

import opsflow.documents.pdf as pdf_module
from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentParseError,
    DocumentValidationError,
)
from opsflow.documents.limits import DEFAULT_DOCUMENT_LIMITS, DocumentLimits
from opsflow.documents.models import (
    CanonicalPage,
    DocumentWarning,
    _ParsedDocumentContent,
)

FIXTURE_DIR = Path("fixtures/documents/pdf")


def _limits(**overrides: int) -> DocumentLimits:
    return replace(DEFAULT_DOCUMENT_LIMITS, **overrides)


def _fixture(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


class _FakePage:
    def __init__(self, extracted_text: str | None) -> None:
        self.extracted_text = extracted_text

    def extract_text(self) -> str | None:
        return self.extracted_text


class _ExplodingPage:
    def extract_text(self) -> str:
        pytest.fail("page text was extracted before the page limit was checked")


class _FakeReader:
    def __init__(self, pages: list[object], *, is_encrypted: bool = False) -> None:
        self.pages = pages
        self.is_encrypted = is_encrypted


def _patch_reader(monkeypatch: pytest.MonkeyPatch, reader: _FakeReader) -> None:
    monkeypatch.setattr(
        pdf_module,
        "PdfReader",
        lambda stream, strict: reader,
    )


def _encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("test-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_parse_single_page_pdf_produces_one_page() -> None:
    parsed = pdf_module.parse_pdf_document(
        _fixture("single-page-text.pdf"),
        DEFAULT_DOCUMENT_LIMITS,
    )

    assert parsed == _ParsedDocumentContent(
        text="Synthetic PDF page one",
        pages=(CanonicalPage(number=1, text="Synthetic PDF page one"),),
        tables=(),
        warnings=(),
    )


def test_parse_multi_page_pdf_preserves_order_and_one_based_numbers() -> None:
    parsed = pdf_module.parse_pdf_document(
        _fixture("multi-page-text.pdf"),
        DEFAULT_DOCUMENT_LIMITS,
    )

    assert parsed.pages == (
        CanonicalPage(number=1, text="Synthetic PDF page one"),
        CanonicalPage(number=2, text="Synthetic PDF page two"),
    )
    assert parsed.text == "Synthetic PDF page one\n\nSynthetic PDF page two"
    assert parsed.tables == ()


@pytest.mark.parametrize("content", [b"plain text", b"PK\x03\x04not a PDF"])
def test_rejects_non_pdf_signature_without_reclassification(content: bytes) -> None:
    with pytest.raises(DocumentValidationError, match="PDF signature"):
        pdf_module.parse_pdf_document(content, DEFAULT_DOCUMENT_LIMITS)


def test_pdf_page_limit_is_checked_before_page_text_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _FakeReader([_ExplodingPage(), _ExplodingPage()])
    _patch_reader(monkeypatch, reader)

    with pytest.raises(DocumentLimitError, match="PDF page limit"):
        pdf_module.parse_pdf_document(
            b"%PDF-1.7\ncontrolled test bytes",
            _limits(max_pdf_pages=1),
        )


def test_corrupt_pdf_with_signature_fails_safely() -> None:
    with pytest.raises(DocumentParseError) as error:
        pdf_module.parse_pdf_document(b"%PDF-1.7\ntruncated", DEFAULT_DOCUMENT_LIMITS)

    assert "truncated" not in str(error.value)
    assert "%PDF" not in str(error.value)


def test_encrypted_pdf_fails_without_password_guessing() -> None:
    with pytest.raises(DocumentParseError, match="encrypted"):
        pdf_module.parse_pdf_document(_encrypted_pdf(), DEFAULT_DOCUMENT_LIMITS)


def test_unreadable_encryption_status_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnreadableEncryptionState:
        @property
        def is_encrypted(self) -> bool:
            raise RuntimeError("private customer content")

    _patch_reader(monkeypatch, UnreadableEncryptionState())  # type: ignore[arg-type]

    with pytest.raises(DocumentParseError) as error:
        pdf_module.parse_pdf_document(
            b"%PDF-1.7\ncontrolled test bytes",
            DEFAULT_DOCUMENT_LIMITS,
        )

    assert "private customer content" not in str(error.value)


def test_text_and_blank_pages_emit_one_empty_page_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reader(monkeypatch, _FakeReader([_FakePage("text"), _FakePage(" \r\n")]))

    parsed = pdf_module.parse_pdf_document(
        b"%PDF-1.7\ncontrolled test bytes",
        DEFAULT_DOCUMENT_LIMITS,
    )

    assert parsed.pages == (
        CanonicalPage(number=1, text="text"),
        CanonicalPage(number=2, text=" \n"),
    )
    assert parsed.warnings == (
        DocumentWarning(
            code="EMPTY_PDF_PAGE",
            message="PDF page contains no extractable text.",
            location="page:2",
        ),
    )
    assert parsed.text == "text"


def test_entirely_blank_pdf_preserves_pages_and_emits_no_text_warning() -> None:
    parsed = pdf_module.parse_pdf_document(_fixture("no-text.pdf"), DEFAULT_DOCUMENT_LIMITS)

    assert parsed.pages == (
        CanonicalPage(number=1, text=""),
        CanonicalPage(number=2, text=""),
    )
    assert parsed.text == ""
    assert parsed.warnings == (
        DocumentWarning(
            code="EMPTY_PDF_PAGE",
            message="PDF page contains no extractable text.",
            location="page:1",
        ),
        DocumentWarning(
            code="EMPTY_PDF_PAGE",
            message="PDF page contains no extractable text.",
            location="page:2",
        ),
        DocumentWarning(
            code="NO_EXTRACTABLE_TEXT",
            message="PDF contains no extractable text on any page.",
            location=None,
        ),
    )


def test_combined_text_joins_only_extractable_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reader(
        monkeypatch,
        _FakeReader([_FakePage("page one"), _FakePage(None), _FakePage("page three")]),
    )

    parsed = pdf_module.parse_pdf_document(
        b"%PDF-1.7\ncontrolled test bytes",
        DEFAULT_DOCUMENT_LIMITS,
    )

    assert parsed.text == "page one\n\npage three"


def test_page_text_uses_shared_conservative_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_reader(monkeypatch, _FakeReader([_FakePage("e\u0301\r\nline\rtext ")]))

    parsed = pdf_module.parse_pdf_document(
        b"%PDF-1.7\ncontrolled test bytes",
        DEFAULT_DOCUMENT_LIMITS,
    )

    assert parsed.pages == (CanonicalPage(number=1, text="é\nline\ntext "),)
    assert parsed.text == "é\nline\ntext "


def test_extraction_failure_is_a_safe_document_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingPage:
        def extract_text(self) -> str:
            raise RuntimeError("private customer content")

    _patch_reader(monkeypatch, _FakeReader([FailingPage()]))

    with pytest.raises(DocumentParseError) as error:
        pdf_module.parse_pdf_document(
            b"%PDF-1.7\ncontrolled test bytes",
            DEFAULT_DOCUMENT_LIMITS,
        )

    assert "private customer content" not in str(error.value)


def test_repeated_parsing_is_equal() -> None:
    content = _fixture("multi-page-text.pdf")

    first = pdf_module.parse_pdf_document(content, DEFAULT_DOCUMENT_LIMITS)
    second = pdf_module.parse_pdf_document(content, DEFAULT_DOCUMENT_LIMITS)

    assert first == second


def test_parser_does_not_need_network_or_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("PDF parsing attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    parsed = pdf_module.parse_pdf_document(
        _fixture("single-page-text.pdf"),
        DEFAULT_DOCUMENT_LIMITS,
    )

    assert parsed.text == "Synthetic PDF page one"
