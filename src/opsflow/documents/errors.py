"""Exceptions raised by the Phase 3 document subsystem."""


class DocumentProcessingError(Exception):
    """Base class for safe, document-specific processing failures."""


class UnsupportedDocumentTypeError(DocumentProcessingError):
    """Raised when a valid source type is outside the Phase 3 parser scope."""


class DocumentValidationError(DocumentProcessingError):
    """Raised when a document input or canonical record violates its contract."""


class DocumentLimitError(DocumentProcessingError):
    """Raised when a configured document-processing limit is exceeded."""


class DocumentParseError(DocumentProcessingError):
    """Raised when document content cannot be decoded or parsed safely."""
