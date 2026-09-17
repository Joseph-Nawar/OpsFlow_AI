"""Internal Phase 3 document-processing contracts."""

from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentParseError,
    DocumentProcessingError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from opsflow.documents.limits import DEFAULT_DOCUMENT_LIMITS, DocumentLimits
from opsflow.documents.models import (
    CanonicalDocument,
    CanonicalPage,
    CanonicalTable,
    DocumentInput,
    DocumentWarning,
)
from opsflow.documents.processor import process_document

__all__ = [
    "DEFAULT_DOCUMENT_LIMITS",
    "CanonicalDocument",
    "CanonicalPage",
    "CanonicalTable",
    "DocumentInput",
    "DocumentLimitError",
    "DocumentLimits",
    "DocumentParseError",
    "DocumentProcessingError",
    "DocumentValidationError",
    "DocumentWarning",
    "UnsupportedDocumentTypeError",
    "process_document",
]
