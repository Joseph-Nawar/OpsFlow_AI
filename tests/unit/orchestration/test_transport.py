import asyncio
from dataclasses import dataclass, field
from typing import cast

import pytest
from fastapi import UploadFile

from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from opsflow.documents.limits import DEFAULT_DOCUMENT_LIMITS
from opsflow.domain import SourceDocumentType
from opsflow.orchestration.contracts import OrchestrationIntakeCommand
from opsflow.orchestration.transport import build_intake_command, read_bounded_upload


@dataclass
class FakeUpload:
    content: bytes
    filename: str | None = "document.pdf"
    content_type: str | None = "application/pdf"
    read_sizes: list[int] = field(default_factory=list)

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.content if size < 0 else self.content[:size]


def _upload(
    *,
    content: bytes = b"document",
    filename: str | None = "document.pdf",
    content_type: str | None = "application/pdf",
) -> FakeUpload:
    return FakeUpload(content=content, filename=filename, content_type=content_type)


def _build(
    upload: FakeUpload,
    *,
    document_type: SourceDocumentType | str = SourceDocumentType.PDF,
    message_id: str | None = "message-1",
    idempotency_key: str = "event-1",
    max_input_bytes: int = 32,
) -> OrchestrationIntakeCommand:
    return asyncio.run(
        build_intake_command(
            cast(UploadFile, upload),
            document_type,
            message_id,
            idempotency_key,
            max_input_bytes=max_input_bytes,
        )
    )


@pytest.mark.parametrize(
    "document_type",
    [
        SourceDocumentType.EMAIL_BODY,
        SourceDocumentType.PDF,
        SourceDocumentType.XLSX,
        SourceDocumentType.CSV,
    ],
)
def test_supported_document_types_are_accepted(document_type: SourceDocumentType) -> None:
    command = _build(_upload(), document_type=document_type)

    assert command.document_type is document_type


def test_form_document_type_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        _build(_upload(), document_type=SourceDocumentType.FORM)


@pytest.mark.parametrize("filename", [None, "", "   ", "/tmp/"])
def test_missing_or_blank_filename_is_rejected(filename: str | None) -> None:
    with pytest.raises(DocumentValidationError):
        _build(_upload(filename=filename))


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("/tmp/invoice.pdf", "invoice.pdf"), (r"C:\\tmp\\invoice.pdf", "invoice.pdf")],
)
def test_filename_discards_unix_and_windows_path_components(filename: str, expected: str) -> None:
    command = _build(_upload(filename=filename))

    assert command.filename == expected


def test_filename_longer_than_255_characters_is_rejected() -> None:
    with pytest.raises(DocumentValidationError):
        _build(_upload(filename="a" * 256))


@pytest.mark.parametrize("content_type", [None, "", "   "])
def test_missing_or_blank_mime_declaration_is_rejected(content_type: str | None) -> None:
    with pytest.raises(DocumentValidationError):
        _build(_upload(content_type=content_type))


def test_none_message_id_is_accepted() -> None:
    command = _build(_upload(), message_id=None)

    assert command.message_id is None


@pytest.mark.parametrize("message_id", ["", "   ", "m" * 257])
def test_blank_or_overlong_message_id_is_rejected(message_id: str) -> None:
    with pytest.raises(DocumentValidationError):
        _build(_upload(), message_id=message_id)


def test_valid_message_id_is_preserved_exactly() -> None:
    message_id = "message/id:2026-09-23"

    command = _build(_upload(), message_id=message_id)

    assert command.message_id == message_id


@pytest.mark.parametrize("idempotency_key", ["", "   ", "k" * 129])
def test_blank_or_overlong_idempotency_key_is_rejected(idempotency_key: str) -> None:
    with pytest.raises(DocumentValidationError):
        _build(_upload(), idempotency_key=idempotency_key)


def test_valid_idempotency_key_is_preserved_exactly() -> None:
    key = "event/id:2026-09-23"

    command = _build(_upload(), idempotency_key=key)

    assert command.idempotency_key == key


def test_exact_maximum_content_is_accepted_and_read_with_max_plus_one() -> None:
    limit = 32
    upload = _upload(content=b"x" * limit)

    content = asyncio.run(read_bounded_upload(cast(UploadFile, upload), limit))

    assert content == b"x" * limit
    assert upload.read_sizes == [limit + 1]


def test_maximum_plus_one_content_is_rejected_without_unbounded_read() -> None:
    limit = 32
    upload = _upload(content=b"x" * (limit + 1))

    with pytest.raises(DocumentLimitError):
        asyncio.run(read_bounded_upload(cast(UploadFile, upload), limit))

    assert upload.read_sizes == [limit + 1]


def test_default_document_limit_is_used_by_intake_command() -> None:
    upload = _upload(content=b"x" * DEFAULT_DOCUMENT_LIMITS.max_input_bytes)

    command = _build(
        upload,
        max_input_bytes=DEFAULT_DOCUMENT_LIMITS.max_input_bytes,
    )

    assert len(command.content) == DEFAULT_DOCUMENT_LIMITS.max_input_bytes
    assert upload.read_sizes == [DEFAULT_DOCUMENT_LIMITS.max_input_bytes + 1]


def test_invalid_transport_is_rejected_before_eventual_handler_call() -> None:
    upload = _upload(content=b"x" * 33)
    handler_called = False

    try:
        _build(upload, max_input_bytes=32)
    except DocumentLimitError:
        pass
    else:
        handler_called = True

    assert handler_called is False
