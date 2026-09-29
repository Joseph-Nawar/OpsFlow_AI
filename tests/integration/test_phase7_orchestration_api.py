"""HTTP integration tests for the Phase 7 orchestration boundary."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.application.errors import IdempotencyConflictError, SourceIdentityMismatchError
from opsflow.application.orchestration import OrchestrationUnavailableError
from opsflow.domain import OrderState, SourceDocumentType
from opsflow.main import create_app
from opsflow.orchestration.contracts import (
    IntakeExecution,
    OrchestrationIntakeCommand,
    OrchestrationIntakeResult,
)
from opsflow.settings import Settings

ORCHESTRATION_TOKEN = "synthetic-orchestration-service-credential"
INTAKE_PATH = "/v1/orchestration/intakes"
PDF_BYTES = b"%PDF-1.7 synthetic orchestration fixture"


def _document_files(
    *, filename: str = "invoice.pdf", content: bytes = PDF_BYTES, mime_type: str = "application/pdf"
) -> dict[str, tuple[str, bytes, str]]:
    return {"document": (filename, content, mime_type)}


def _result(
    *,
    state: OrderState = OrderState.NEEDS_REVIEW,
    idempotent_replay: bool = False,
    execution: IntakeExecution = IntakeExecution.COMPLETED,
) -> OrchestrationIntakeResult:
    return OrchestrationIntakeResult(
        order_id=UUID("00000000-0000-0000-0000-000000000007"),
        state=state,
        failure_origin=None,
        idempotent_replay=idempotent_replay,
        execution=execution,
    )


def test_openapi_exposes_exactly_the_phase7_intake_boundary() -> None:
    openapi = create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN)).openapi()
    paths = openapi["paths"]

    assert set(path for path in paths if path.startswith("/v1/orchestration")) == {INTAKE_PATH}
    operation = paths[INTAKE_PATH]["post"]
    assert set(paths[INTAKE_PATH]) == {"post"}
    assert "multipart/form-data" in operation["requestBody"]["content"]
    idempotency_parameters = [
        parameter for parameter in operation["parameters"] if parameter["name"] == "Idempotency-Key"
    ]
    assert len(idempotency_parameters) == 1
    assert idempotency_parameters[0]["in"] == "header"
    assert idempotency_parameters[0]["required"] is True

    request_schema = _resolve_schema(
        openapi,
        operation["requestBody"]["content"]["multipart/form-data"]["schema"],
    )
    assert set(request_schema["properties"]) == {
        "document",
        "document_type",
        "message_id",
        "source_system",
    }
    assert (
        request_schema["properties"]["document"]["contentMediaType"] == "application/octet-stream"
    )
    assert request_schema["properties"]["document_type"]["type"] == "string"
    assert request_schema["properties"]["message_id"]["anyOf"][0]["type"] == "string"
    assert "message_id" not in request_schema["required"]
    assert "source_system" not in request_schema["required"]
    assert "document_type" in request_schema["required"]
    assert operation["security"]
    response_schema = _resolve_schema(
        openapi,
        operation["responses"]["200"]["content"]["application/json"]["schema"],
    )
    assert set(response_schema["properties"]) == {
        "order_id",
        "state",
        "failure_origin",
        "idempotent_replay",
    }
    assert "execution" not in response_schema["properties"]


def test_app_initializes_the_orchestration_runtime_and_handler() -> None:
    app = create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN))

    assert app.state.orchestration_token is not None
    assert app.state.orchestration_runtime is not None
    assert callable(app.state.orchestration_intake_handler)
    assert (
        app.state.orchestration_runtime.business_data_provider is app.state.review_runtime.provider
    )
    assert app.state.orchestration_runtime.policy is app.state.review_runtime.policy
    assert app.state.orchestration_runtime.date_provider is app.state.review_runtime.date_provider


def test_valid_request_with_explicitly_absent_handler_keeps_defensive_503() -> None:
    response = asyncio.run(_post(remove_handler=True))

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ORCHESTRATION_UNAVAILABLE"


@pytest.mark.parametrize(
    ("data", "files", "secret"),
    [
        ({"document_type": "PDF"}, {}, "raw document bytes"),
        ({"document_type": "NOT_A_SOURCE_TYPE"}, _document_files(), "raw document bytes"),
        ({"document_type": "FORM"}, _document_files(), "raw document bytes"),
    ],
)
def test_malformed_multipart_or_document_type_returns_bounded_422_without_echoing(
    data: dict[str, str], files: dict[str, tuple[str, bytes, str]], secret: str
) -> None:
    response = asyncio.run(_post(data=data, files=files, content_secret=secret))

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "INVALID_ORCHESTRATION_INTAKE",
            "message": "The orchestration intake request is invalid.",
        }
    }
    assert secret not in response.text


def test_blank_idempotency_key_returns_422_without_calling_the_handler() -> None:
    stub = RecordingHandler(_result())
    response = asyncio.run(_post_with_handler(stub, idempotency_key=" "))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ORCHESTRATION_INTAKE"
    assert stub.calls == []


def test_missing_idempotency_key_returns_422_without_calling_the_handler() -> None:
    stub = RecordingHandler(_result())
    response = asyncio.run(_post_with_handler(stub, include_idempotency_key=False))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ORCHESTRATION_INTAKE"
    assert stub.calls == []


def test_oversized_document_returns_422_without_calling_the_handler() -> None:
    stub = RecordingHandler(_result())
    response = asyncio.run(
        _post_with_handler(stub, content=b"x" * (10 * 1024 * 1024 + 1), filename="large.pdf")
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ORCHESTRATION_INTAKE"
    assert stub.calls == []


def test_valid_request_without_handler_returns_safe_503() -> None:
    response = asyncio.run(_post(remove_handler=True))

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "ORCHESTRATION_UNAVAILABLE",
            "message": "Orchestration intake is currently unavailable.",
        }
    }
    assert PDF_BYTES.decode() not in response.text
    assert ORCHESTRATION_TOKEN not in response.text


def test_valid_request_forwards_exact_command_actor_session_and_timestamp() -> None:
    stub = RecordingHandler(_result())
    response = asyncio.run(
        _post_with_handler(
            stub,
            filename=r"incoming\invoice.pdf",
            data={"document_type": "PDF", "actor": "forged-form-actor", "role": "ADMIN"},
            message_id="message-id-001",
            idempotency_key="key-unchanged-001",
            extra_headers={"X-Actor": "forged-header-actor", "X-Role": "ADMIN"},
        )
    )

    assert response.status_code == 201
    assert len(stub.calls) == 1
    session, command, actor, recorded_at = stub.calls[0]
    assert isinstance(session, AsyncSession)
    assert isinstance(command, OrchestrationIntakeCommand)
    assert command.content == PDF_BYTES
    assert command.document_type is SourceDocumentType.PDF
    assert command.filename == "invoice.pdf"
    assert command.mime_type == "application/pdf"
    assert command.message_id == "message-id-001"
    assert command.idempotency_key == "key-unchanged-001"
    assert command.source_system is None
    assert actor == "orchestration:n8n"
    assert isinstance(recorded_at, datetime)
    assert recorded_at.tzinfo is UTC


def test_valid_gmail_provenance_is_forwarded_without_rewriting_identity() -> None:
    stub = RecordingHandler(_result())
    response = asyncio.run(
        _post_with_handler(
            stub,
            source_system="GMAIL",
            message_id="gmail-message-001",
            idempotency_key="gmail:gmail-message-001",
        )
    )

    assert response.status_code == 201
    assert stub.calls[0][1].source_system == "GMAIL"
    assert stub.calls[0][1].message_id == "gmail-message-001"
    assert stub.calls[0][1].idempotency_key == "gmail:gmail-message-001"


@pytest.mark.parametrize(
    ("source_system", "message_id", "idempotency_key"),
    [
        ("GMAIL", None, "gmail:message-001"),
        ("GMAIL", "   ", "gmail:   "),
        ("GMAIL", "message-001", "wrong-key"),
        ("OUTLOOK", "message-001", "outlook:message-001"),
    ],
)
def test_invalid_gmail_provenance_returns_bounded_422_without_handler_call(
    source_system: str,
    message_id: str | None,
    idempotency_key: str,
) -> None:
    stub = RecordingHandler(_result())
    response = asyncio.run(
        _post_with_handler(
            stub,
            source_system=source_system,
            message_id=message_id,
            idempotency_key=idempotency_key,
        )
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "INVALID_ORCHESTRATION_INTAKE",
            "message": "The orchestration intake request is invalid.",
        }
    }
    assert stub.calls == []


def test_overlong_gmail_prefixed_key_returns_bounded_422() -> None:
    message_id = "m" * 123
    response = asyncio.run(
        _post_with_handler(
            RecordingHandler(_result()),
            source_system="GMAIL",
            message_id=message_id,
            idempotency_key=f"gmail:{message_id}",
        )
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ORCHESTRATION_INTAKE"
    assert message_id not in response.text


@pytest.mark.parametrize(
    ("result", "expected_status"),
    [
        (
            _result(
                state=OrderState.NEEDS_REVIEW,
                idempotent_replay=False,
                execution=IntakeExecution.COMPLETED,
            ),
            201,
        ),
        (
            _result(
                state=OrderState.NEEDS_REVIEW,
                idempotent_replay=True,
                execution=IntakeExecution.COMPLETED,
            ),
            200,
        ),
        (
            _result(
                state=OrderState.PROCESSING,
                idempotent_replay=True,
                execution=IntakeExecution.STANDING_DOWN,
            ),
            202,
        ),
        (
            _result(
                state=OrderState.EXTRACTED,
                idempotent_replay=True,
                execution=IntakeExecution.STANDING_DOWN,
            ),
            202,
        ),
        (
            _result(
                state=OrderState.PROCESSING,
                idempotent_replay=False,
                execution=IntakeExecution.STANDING_DOWN,
            ),
            202,
        ),
        (
            _result(state=OrderState.FAILED_RETRYABLE, execution=IntakeExecution.STANDING_DOWN),
            200,
        ),
        (
            _result(
                state=OrderState.FAILED_RETRYABLE,
                idempotent_replay=True,
                execution=IntakeExecution.STANDING_DOWN,
            ),
            200,
        ),
    ],
)
def test_result_execution_maps_to_the_approved_http_status(
    result: OrchestrationIntakeResult, expected_status: int
) -> None:
    response = asyncio.run(_post_with_handler(RecordingHandler(result)))

    assert response.status_code == expected_status
    assert set(response.json()) == {
        "order_id",
        "state",
        "failure_origin",
        "idempotent_replay",
    }
    assert "execution" not in response.json()


@pytest.mark.parametrize(
    "state",
    [OrderState.RECEIVED, OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.VALIDATED],
)
def test_completed_intermediate_result_returns_safe_503(state: OrderState) -> None:
    response = asyncio.run(
        _post_with_handler(
            RecordingHandler(
                _result(
                    state=state,
                    idempotent_replay=True,
                    execution=IntakeExecution.COMPLETED,
                )
            )
        )
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "ORCHESTRATION_UNAVAILABLE",
            "message": "Orchestration intake is currently unavailable.",
        }
    }


def test_idempotency_conflict_maps_to_safe_409() -> None:
    secret = "different-source-secret"
    response = asyncio.run(_post_with_handler(RaisingHandler(IdempotencyConflictError(secret))))

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "Idempotency key was already used for a different request.",
        }
    }
    assert secret not in response.text


def test_source_identity_conflict_maps_to_safe_409() -> None:
    secret = "source-conflict-secret"
    stub = RaisingHandler(SourceIdentityMismatchError(uuid4(), uuid4()))
    response = asyncio.run(_post_with_handler(stub, content_secret=secret))

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SOURCE_IDENTITY_CONFLICT"
    assert secret not in response.text


def test_handler_unavailable_error_maps_to_bounded_503() -> None:
    response = asyncio.run(_post_with_handler(RaisingHandler(OrchestrationUnavailableError())))

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "ORCHESTRATION_UNAVAILABLE",
            "message": "Orchestration intake is currently unavailable.",
        }
    }


def test_malformed_input_short_circuits_before_the_handler() -> None:
    stub = RecordingHandler(_result())
    response = asyncio.run(
        _post_with_handler(
            stub,
            data={"document_type": "FORM"},
            content=b"private raw source bytes",
            content_secret="private raw source bytes",
        )
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ORCHESTRATION_INTAKE"
    assert stub.calls == []
    assert "private raw source bytes" not in response.text


class RecordingHandler:
    def __init__(self, result: OrchestrationIntakeResult) -> None:
        self.result = result
        self.calls: list[tuple[AsyncSession, OrchestrationIntakeCommand, str, datetime]] = []

    async def __call__(
        self,
        session: AsyncSession,
        command: OrchestrationIntakeCommand,
        actor: str,
        recorded_at: datetime,
    ) -> OrchestrationIntakeResult:
        self.calls.append((session, command, actor, recorded_at))
        return self.result


class RaisingHandler:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def __call__(self, *args: Any, **kwargs: Any) -> OrchestrationIntakeResult:
        del args, kwargs
        raise self.error


async def _post(
    *,
    data: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    idempotency_key: str = "api-test-key",
    content_secret: str | None = None,
    remove_handler: bool = False,
) -> httpx.Response:
    app = create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN))
    if remove_handler:
        app.state.orchestration_intake_handler = None
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {
                "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                "Idempotency-Key": idempotency_key,
            }
            if files == {}:
                headers["Content-Type"] = "application/octet-stream"
                return await client.post(
                    INTAKE_PATH,
                    content=(content_secret or "").encode(),
                    headers=headers,
                )
            return await client.post(
                INTAKE_PATH,
                data=data if data is not None else {"document_type": "PDF"},
                files=files if files is not None else _document_files(),
                headers=headers,
            )


async def _post_with_handler(
    handler: Callable[..., Awaitable[OrchestrationIntakeResult]],
    *,
    data: dict[str, str] | None = None,
    content: bytes = PDF_BYTES,
    filename: str = "invoice.pdf",
    message_id: str | None = "message-id-001",
    source_system: str | None = None,
    idempotency_key: str = "api-test-key",
    include_idempotency_key: bool = True,
    extra_headers: dict[str, str] | None = None,
    content_secret: str | None = None,
) -> httpx.Response:
    del content_secret
    app = create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN))
    app.state.orchestration_intake_handler = handler
    form = data if data is not None else {"document_type": "PDF"}
    if message_id is not None:
        form["message_id"] = message_id
    if source_system is not None:
        form["source_system"] = source_system
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"Authorization": f"Bearer {ORCHESTRATION_TOKEN}"}
            if include_idempotency_key:
                headers["Idempotency-Key"] = idempotency_key
            if extra_headers is not None:
                headers.update(extra_headers)
            return await client.post(
                INTAKE_PATH,
                data=form,
                files=_document_files(filename=filename, content=content),
                headers=headers,
            )


def _resolve_schema(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    name = reference.rsplit("/", 1)[-1]
    return openapi["components"]["schemas"][name]
