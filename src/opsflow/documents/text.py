"""Deterministic parser for plain text and email-body document content."""

from opsflow.documents.common import decode_utf8, normalize_text
from opsflow.documents.models import DocumentWarning, _ParsedDocumentContent


def parse_text_document(content: bytes) -> _ParsedDocumentContent:
    """Decode and conservatively normalize one plain-text document body."""
    text = normalize_text(decode_utf8(content))
    warnings: tuple[DocumentWarning, ...] = ()
    if not text.strip():
        warnings = (
            DocumentWarning(
                code="EMPTY_TEXT",
                message="Document contains no non-whitespace text.",
            ),
        )
    return _ParsedDocumentContent(text=text, warnings=warnings)
