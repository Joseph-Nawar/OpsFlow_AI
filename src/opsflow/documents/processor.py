"""Synchronous Phase 3 document dispatcher and canonical envelope builder."""

from opsflow.documents.common import normalize_mime_type, sha256_bytes
from opsflow.documents.csv import parse_csv_document
from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from opsflow.documents.limits import DEFAULT_DOCUMENT_LIMITS, DocumentLimits
from opsflow.documents.models import CanonicalDocument, DocumentInput
from opsflow.documents.pdf import parse_pdf_document
from opsflow.documents.text import parse_text_document
from opsflow.documents.xlsx import parse_xlsx_document
from opsflow.domain.records import SourceDocumentType

_EXPECTED_MIME_TYPES = {
    SourceDocumentType.EMAIL_BODY: "text/plain",
    SourceDocumentType.CSV: "text/csv",
    SourceDocumentType.PDF: "application/pdf",
    SourceDocumentType.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def process_document(
    document: DocumentInput,
    limits: DocumentLimits = DEFAULT_DOCUMENT_LIMITS,
) -> CanonicalDocument:
    """Process one validated document input into a canonical result."""
    if document.document_type is SourceDocumentType.FORM:
        raise UnsupportedDocumentTypeError("FORM documents are not supported by Phase 3")

    normalized_mime_type = normalize_mime_type(document.mime_type)
    expected_mime_type = _EXPECTED_MIME_TYPES.get(document.document_type)
    if expected_mime_type is None:
        raise UnsupportedDocumentTypeError(
            f"document type {document.document_type.value!r} is not supported by Phase 3"
        )
    if normalized_mime_type != expected_mime_type:
        raise DocumentValidationError(
            f"MIME type {normalized_mime_type!r} does not match the declared document type"
        )
    if len(document.content) > limits.max_input_bytes:
        raise DocumentLimitError("document input byte limit exceeded")

    source_sha256 = sha256_bytes(document.content)
    if document.document_type is SourceDocumentType.EMAIL_BODY:
        parsed = parse_text_document(document.content)
    elif document.document_type is SourceDocumentType.CSV:
        parsed = parse_csv_document(document.content, limits)
    elif document.document_type is SourceDocumentType.XLSX:
        parsed = parse_xlsx_document(document.content, limits)
    elif document.document_type is SourceDocumentType.PDF:
        parsed = parse_pdf_document(document.content, limits)
    else:
        raise UnsupportedDocumentTypeError(
            f"document type {document.document_type.value!r} is not supported by Phase 3"
        )

    if len(parsed.text) > limits.max_text_characters:
        raise DocumentLimitError("canonical text character limit exceeded")

    return CanonicalDocument(
        document_type=document.document_type,
        name=document.name,
        mime_type=normalized_mime_type,
        sha256=source_sha256,
        size_bytes=len(document.content),
        source_reference=document.source_reference,
        metadata=document.metadata,
        text=parsed.text,
        pages=parsed.pages,
        tables=parsed.tables,
        warnings=parsed.warnings,
    )


__all__ = ["process_document"]
