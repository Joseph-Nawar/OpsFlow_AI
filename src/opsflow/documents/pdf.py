"""Deterministic text extraction for Phase 3 PDF documents."""

import io

from pypdf import PdfReader

from opsflow.documents.common import normalize_text
from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentParseError,
    DocumentProcessingError,
    DocumentValidationError,
)
from opsflow.documents.limits import DocumentLimits
from opsflow.documents.models import CanonicalPage, DocumentWarning, _ParsedDocumentContent


def _read_pdf(content: bytes) -> PdfReader:
    try:
        return PdfReader(io.BytesIO(content), strict=True)
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentParseError("PDF could not be parsed") from exc


def parse_pdf_document(
    content: bytes,
    limits: DocumentLimits,
) -> _ParsedDocumentContent:
    """Parse PDF page text while preserving page boundaries and warnings."""
    if not isinstance(content, bytes):
        raise DocumentValidationError("PDF content must be bytes")
    if not content.startswith(b"%PDF-"):
        raise DocumentValidationError("PDF signature is invalid")

    reader = _read_pdf(content)
    try:
        encrypted = reader.is_encrypted
    except Exception as exc:
        raise DocumentParseError("PDF encryption status could not be read") from exc
    if encrypted:
        raise DocumentParseError("encrypted PDFs are not supported")

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise DocumentParseError("PDF page count could not be read") from exc
    if page_count > limits.max_pdf_pages:
        raise DocumentLimitError("PDF page limit exceeded")

    pages: list[CanonicalPage] = []
    warnings: list[DocumentWarning] = []
    try:
        for index, page in enumerate(reader.pages, start=1):
            extracted_text = page.extract_text()
            if extracted_text is None:
                extracted_text = ""
            if not isinstance(extracted_text, str):
                raise DocumentParseError("PDF page text extraction returned invalid data")
            normalized_text = normalize_text(extracted_text)
            pages.append(CanonicalPage(number=index, text=normalized_text))
            if not normalized_text.strip():
                warnings.append(
                    DocumentWarning(
                        code="EMPTY_PDF_PAGE",
                        message="PDF page contains no extractable text.",
                        location=f"page:{index}",
                    )
                )
    except DocumentProcessingError:
        raise
    except Exception as exc:
        raise DocumentParseError("PDF page text extraction failed") from exc

    if not any(page.text.strip() for page in pages):
        warnings.append(
            DocumentWarning(
                code="NO_EXTRACTABLE_TEXT",
                message="PDF contains no extractable text on any page.",
            )
        )

    combined_text = "\n\n".join(page.text for page in pages if page.text.strip())
    return _ParsedDocumentContent(
        text=combined_text,
        pages=tuple(pages),
        warnings=tuple(warnings),
    )


__all__ = ["parse_pdf_document"]
