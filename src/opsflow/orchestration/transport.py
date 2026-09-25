"""Validation and bounded reading for the orchestration multipart seam."""

from fastapi import UploadFile

from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from opsflow.documents.limits import DEFAULT_DOCUMENT_LIMITS
from opsflow.domain import SourceDocumentType

from .contracts import OrchestrationIntakeCommand

_MAX_FILENAME_CHARACTERS = 255
_MAX_MESSAGE_ID_CHARACTERS = 256
_MAX_IDEMPOTENCY_KEY_CHARACTERS = 128


async def read_bounded_upload(upload: UploadFile, max_input_bytes: int) -> bytes:
    """Read at most one byte beyond the configured document limit."""

    if (
        not isinstance(max_input_bytes, int)
        or isinstance(max_input_bytes, bool)
        or max_input_bytes <= 0
    ):
        raise DocumentValidationError("max_input_bytes must be a positive integer")

    content = await upload.read(max_input_bytes + 1)
    if len(content) > max_input_bytes:
        raise DocumentLimitError("document exceeds the maximum input size")
    return content


async def build_intake_command(
    upload: UploadFile,
    document_type: SourceDocumentType | str,
    message_id: str | None,
    idempotency_key: str,
    *,
    source_system: str | None = None,
    max_input_bytes: int = DEFAULT_DOCUMENT_LIMITS.max_input_bytes,
) -> OrchestrationIntakeCommand:
    """Validate multipart metadata and retain accepted bytes for this request."""

    resolved_document_type = _resolve_document_type(document_type)
    filename = _basename(upload.filename)
    mime_type = _validated_mime_type(upload.content_type)
    _validate_message_id(message_id)
    _validate_idempotency_key(idempotency_key)
    _validate_source_provenance(source_system, message_id, idempotency_key)
    content = await read_bounded_upload(upload, max_input_bytes)
    return OrchestrationIntakeCommand(
        content=content,
        document_type=resolved_document_type,
        filename=filename,
        mime_type=mime_type,
        message_id=message_id,
        idempotency_key=idempotency_key,
        source_system=source_system,
    )


def _resolve_document_type(value: SourceDocumentType | str) -> SourceDocumentType:
    if isinstance(value, SourceDocumentType):
        resolved = value
    elif isinstance(value, str):
        try:
            resolved = SourceDocumentType(value)
        except ValueError as error:
            raise DocumentValidationError("document_type is not supported") from error
    else:
        raise DocumentValidationError("document_type is not supported")

    if resolved is SourceDocumentType.FORM:
        raise UnsupportedDocumentTypeError("FORM is not supported by orchestration intake")
    return resolved


def _basename(filename: str | None) -> str:
    if not isinstance(filename, str):
        raise DocumentValidationError("filename must be a nonblank string")
    basename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not basename.strip():
        raise DocumentValidationError("filename must be a nonblank string")
    if len(basename) > _MAX_FILENAME_CHARACTERS:
        raise DocumentValidationError("filename exceeds 255 characters")
    return basename


def _validated_mime_type(mime_type: str | None) -> str:
    if not isinstance(mime_type, str) or not mime_type.strip():
        raise DocumentValidationError("mime_type must be a nonblank string")
    return mime_type


def _validate_message_id(message_id: str | None) -> None:
    if message_id is None:
        return
    if not isinstance(message_id, str) or not message_id.strip():
        raise DocumentValidationError("message_id must be a nonblank string or None")
    if len(message_id) > _MAX_MESSAGE_ID_CHARACTERS:
        raise DocumentValidationError("message_id exceeds 256 characters")


def _validate_idempotency_key(idempotency_key: str) -> None:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise DocumentValidationError("idempotency key must be a nonblank string")
    if len(idempotency_key) > _MAX_IDEMPOTENCY_KEY_CHARACTERS:
        raise DocumentValidationError("idempotency key exceeds 128 characters")


def _validate_source_provenance(
    source_system: str | None,
    message_id: str | None,
    idempotency_key: str,
) -> None:
    if source_system is None:
        return
    if source_system != "GMAIL":
        raise DocumentValidationError("source_system is not supported")
    if message_id is None or not message_id.strip():
        raise DocumentValidationError("GMAIL source requires a nonblank message_id")
    if idempotency_key != f"gmail:{message_id}":
        raise DocumentValidationError("GMAIL source requires its exact message idempotency key")
