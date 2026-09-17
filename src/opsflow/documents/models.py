"""Immutable records for Phase 3 document inputs and canonical output."""

import re
from dataclasses import dataclass

from opsflow.documents.errors import DocumentValidationError
from opsflow.domain.records import SourceDocumentType


def _require_non_blank_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DocumentValidationError(f"{name} must be a nonblank string")


def _require_metadata(value: object, name: str = "metadata") -> None:
    if not isinstance(value, tuple):
        raise DocumentValidationError(f"{name} must be a tuple of string pairs")
    for entry in value:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not isinstance(entry[1], str)
        ):
            raise DocumentValidationError(f"{name} must be a tuple of string pairs")


def _require_nonnegative_integer(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DocumentValidationError(f"{name} must be a nonnegative integer")


def _require_pages(value: object, name: str = "pages") -> None:
    if not isinstance(value, tuple):
        raise DocumentValidationError(f"{name} must be a tuple of CanonicalPage")
    if any(not isinstance(page, CanonicalPage) for page in value):
        raise DocumentValidationError(f"{name} must be a tuple of CanonicalPage")


def _require_tables(value: object, name: str = "tables") -> None:
    if not isinstance(value, tuple):
        raise DocumentValidationError(f"{name} must be a tuple of CanonicalTable")
    if any(not isinstance(table, CanonicalTable) for table in value):
        raise DocumentValidationError(f"{name} must be a tuple of CanonicalTable")


def _require_warnings(value: object, name: str = "warnings") -> None:
    if not isinstance(value, tuple):
        raise DocumentValidationError(f"{name} must be a tuple of DocumentWarning")
    if any(not isinstance(warning, DocumentWarning) for warning in value):
        raise DocumentValidationError(f"{name} must be a tuple of DocumentWarning")


@dataclass(frozen=True, slots=True)
class DocumentInput:
    """Immutable input envelope accepted by the internal processor."""

    document_type: SourceDocumentType
    name: str
    mime_type: str
    content: bytes
    source_reference: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.document_type, SourceDocumentType):
            raise DocumentValidationError("document_type must be a SourceDocumentType")
        _require_non_blank_string("name", self.name)
        _require_non_blank_string("mime_type", self.mime_type)
        if not isinstance(self.content, bytes):
            raise DocumentValidationError("content must be bytes")
        if self.source_reference is not None and not isinstance(self.source_reference, str):
            raise DocumentValidationError("source_reference must be a string or None")
        _require_metadata(self.metadata)


@dataclass(frozen=True, slots=True)
class CanonicalPage:
    """One 1-based page of canonical extracted text."""

    number: int
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.number, int) or isinstance(self.number, bool) or self.number < 1:
            raise DocumentValidationError("page number must be a positive integer")
        if not isinstance(self.text, str):
            raise DocumentValidationError("page text must be a string")


@dataclass(frozen=True, slots=True)
class CanonicalTable:
    """Ordered canonical table rows; rows may legitimately be ragged."""

    name: str
    rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        _require_non_blank_string("table name", self.name)
        if not isinstance(self.rows, tuple):
            raise DocumentValidationError("table rows must be a tuple")
        for row in self.rows:
            if not isinstance(row, tuple):
                raise DocumentValidationError("each table row must be a tuple")
            if any(not isinstance(cell, str) for cell in row):
                raise DocumentValidationError("each table cell must be a string")


@dataclass(frozen=True, slots=True)
class DocumentWarning:
    """Stable, human-readable warning attached to canonical output."""

    code: str
    message: str
    location: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank_string("warning code", self.code)
        _require_non_blank_string("warning message", self.message)
        if self.location is not None and not isinstance(self.location, str):
            raise DocumentValidationError("warning location must be a string or None")


@dataclass(frozen=True, slots=True)
class CanonicalDocument:
    """Complete deterministic canonical representation of one source."""

    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    size_bytes: int
    source_reference: str | None
    metadata: tuple[tuple[str, str], ...]
    text: str
    pages: tuple[CanonicalPage, ...]
    tables: tuple[CanonicalTable, ...]
    warnings: tuple[DocumentWarning, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.document_type, SourceDocumentType):
            raise DocumentValidationError("document_type must be a SourceDocumentType")
        _require_non_blank_string("name", self.name)
        _require_non_blank_string("mime_type", self.mime_type)
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise DocumentValidationError("sha256 must be a lowercase SHA-256 hex digest")
        _require_nonnegative_integer("size_bytes", self.size_bytes)
        if self.source_reference is not None and not isinstance(self.source_reference, str):
            raise DocumentValidationError("source_reference must be a string or None")
        _require_metadata(self.metadata)
        if not isinstance(self.text, str):
            raise DocumentValidationError("canonical text must be a string")
        _require_pages(self.pages)
        _require_tables(self.tables)
        _require_warnings(self.warnings)


@dataclass(frozen=True, slots=True)
class _ParsedDocumentContent:
    """Private parser result finalized by the future public dispatcher."""

    text: str
    pages: tuple[CanonicalPage, ...] = ()
    tables: tuple[CanonicalTable, ...] = ()
    warnings: tuple[DocumentWarning, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise DocumentValidationError("parsed text must be a string")
        _require_pages(self.pages)
        _require_tables(self.tables)
        _require_warnings(self.warnings)


__all__ = [
    "CanonicalDocument",
    "CanonicalPage",
    "CanonicalTable",
    "DocumentInput",
    "DocumentWarning",
]
