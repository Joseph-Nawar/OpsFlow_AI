from dataclasses import FrozenInstanceError, fields

import pytest

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
from opsflow.domain.records import SourceDocumentType


def test_document_input_preserves_duplicate_metadata_order() -> None:
    metadata = (("source", "mailbox"), ("tag", "one"), ("tag", "two"))

    document = DocumentInput(
        document_type=SourceDocumentType.EMAIL_BODY,
        name="order.txt",
        mime_type="text/plain",
        content=b"SKU,Quantity",
        source_reference="message-1",
        metadata=metadata,
    )

    assert document.metadata == metadata
    assert document.source_reference == "message-1"


def test_document_input_rejects_non_enum_document_type() -> None:
    with pytest.raises(DocumentValidationError, match="document_type"):
        DocumentInput(
            document_type="XML",  # type: ignore[arg-type]
            name="order.xml",
            mime_type="application/xml",
            content=b"<order />",
        )


def test_document_input_accepts_form_for_later_dispatch_rejection() -> None:
    document = DocumentInput(
        document_type=SourceDocumentType.FORM,
        name="order-form",
        mime_type="application/octet-stream",
        content=b"form content",
    )

    assert document.document_type is SourceDocumentType.FORM


def test_document_records_are_frozen_and_slot_based() -> None:
    records = (
        DocumentInput(
            document_type=SourceDocumentType.CSV,
            name="orders.csv",
            mime_type="text/csv",
            content=b"A,B\n1,2",
        ),
        CanonicalPage(number=1, text="page"),
        CanonicalTable(name="CSV", rows=(("A", "B"),)),
        DocumentWarning(code="EMPTY_TEXT", message="No text was present."),
    )

    for record in records:
        with pytest.raises(FrozenInstanceError):
            setattr(record, fields(record)[0].name, object())
        assert not hasattr(record, "__dict__")


def test_canonical_page_numbers_are_one_based() -> None:
    assert CanonicalPage(number=1, text="first").number == 1

    with pytest.raises(DocumentValidationError, match="page number"):
        CanonicalPage(number=0, text="invalid")


def test_canonical_table_preserves_ragged_rows_and_empty_cells() -> None:
    rows = (("A", "B"), ("1",), ("2", "3", ""))

    table = CanonicalTable(name="CSV", rows=rows)

    assert table.rows == rows


def test_document_warning_requires_stable_code_and_message() -> None:
    warning = DocumentWarning(
        code="EMPTY_TEXT", message="The document contains no non-whitespace text."
    )

    assert warning.code == "EMPTY_TEXT"
    assert warning.message == "The document contains no non-whitespace text."

    with pytest.raises(DocumentValidationError, match="warning code"):
        DocumentWarning(code=" ", message="safe message")
    with pytest.raises(DocumentValidationError, match="warning message"):
        DocumentWarning(code="SAFE", message="")


def test_document_limits_match_approved_defaults() -> None:
    assert (
        DocumentLimits(
            max_input_bytes=10 * 1024 * 1024,
            max_text_characters=1_000_000,
            max_pdf_pages=50,
            max_xlsx_sheets=20,
            max_xlsx_rows_per_sheet=5_000,
            max_xlsx_populated_cells=20_000,
            max_csv_rows=5_000,
            max_table_columns=100,
            max_xlsx_expanded_bytes=50 * 1024 * 1024,
        )
        == DEFAULT_DOCUMENT_LIMITS
    )


def test_document_limits_reject_nonpositive_values() -> None:
    values = {
        "max_input_bytes": 0,
        "max_text_characters": 1,
        "max_pdf_pages": 1,
        "max_xlsx_sheets": 1,
        "max_xlsx_rows_per_sheet": 1,
        "max_xlsx_populated_cells": 1,
        "max_csv_rows": 1,
        "max_table_columns": 1,
        "max_xlsx_expanded_bytes": 1,
    }

    with pytest.raises(DocumentValidationError, match="max_input_bytes"):
        DocumentLimits(**{**values, "max_input_bytes": 0})

    with pytest.raises(DocumentValidationError, match="positive"):
        DocumentLimits(**{**values, "max_table_columns": -1})


def test_canonical_document_rejects_invalid_nested_records() -> None:
    with pytest.raises(DocumentValidationError, match="pages"):
        CanonicalDocument(
            document_type=SourceDocumentType.EMAIL_BODY,
            name="body.txt",
            mime_type="text/plain",
            sha256="0" * 64,
            size_bytes=0,
            source_reference=None,
            metadata=(),
            text="",
            pages=("not a page",),  # type: ignore[arg-type]
            tables=(),
            warnings=(),
        )


def test_document_errors_are_document_specific_and_safe() -> None:
    errors = (
        UnsupportedDocumentTypeError("document type is not supported"),
        DocumentValidationError("document metadata is invalid"),
        DocumentLimitError("document exceeds configured limit"),
        DocumentParseError("document could not be parsed"),
    )

    for error in errors:
        assert isinstance(error, DocumentProcessingError)
        assert "private-document-body" not in str(error)
