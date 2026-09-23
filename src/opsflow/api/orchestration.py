"""Authenticated transport boundary for future orchestration intake."""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from opsflow.application.errors import (
    IdempotencyConflictError,
    SourceIdentityMismatchError,
    SourceOwnershipError,
)
from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from opsflow.domain import OrderState
from opsflow.orchestration.auth import get_orchestration_actor
from opsflow.orchestration.contracts import (
    IntakeExecution,
    OrchestrationIntakeHandler,
    OrchestrationIntakeResult,
)
from opsflow.orchestration.transport import build_intake_command

from .orchestration_schemas import OrchestrationIntakeResponse
from .orders import SessionDependency


class _OrchestrationRoute(APIRoute):
    """Keep malformed orchestration requests in a bounded non-echoing shape."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": "INVALID_ORCHESTRATION_INTAKE",
                            "message": "The orchestration intake request is invalid.",
                        }
                    },
                )

        return handler


router = APIRouter(
    prefix="/v1/orchestration",
    tags=["orchestration"],
    route_class=_OrchestrationRoute,
)
OrchestrationActorDependency = Annotated[str, Depends(get_orchestration_actor)]


@router.post("/intakes", response_model=OrchestrationIntakeResponse)
async def create_orchestration_intake_endpoint(
    request: Request,
    document: Annotated[UploadFile, File(...)],
    document_type: Annotated[str, Form(...)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    actor: OrchestrationActorDependency,
    session: SessionDependency,
    response: Response,
    message_id: Annotated[str | None, Form()] = None,
) -> OrchestrationIntakeResponse:
    """Accept one authenticated document without claiming pipeline execution."""

    try:
        command = await build_intake_command(
            document,
            document_type,
            message_id,
            idempotency_key,
        )
    except (DocumentLimitError, DocumentValidationError, UnsupportedDocumentTypeError) as error:
        raise _invalid_intake() from error

    handler = cast(
        OrchestrationIntakeHandler | None,
        request.app.state.orchestration_intake_handler,
    )
    if handler is None:
        raise _orchestration_unavailable()

    try:
        result = await handler(session, command, actor, datetime.now(UTC))
    except IdempotencyConflictError as error:
        raise _idempotency_conflict() from error
    except (SourceIdentityMismatchError, SourceOwnershipError) as error:
        raise _source_identity_conflict() from error

    response.status_code = _status_for_result(result)
    return OrchestrationIntakeResponse(
        order_id=result.order_id,
        state=result.state,
        failure_origin=result.failure_origin,
        idempotent_replay=result.idempotent_replay,
    )


def _status_for_result(result: OrchestrationIntakeResult) -> int:
    if result.idempotent_replay:
        return 200
    if result.execution is IntakeExecution.COMPLETED:
        return 201
    if result.execution is IntakeExecution.STANDING_DOWN:
        if result.state in {OrderState.PROCESSING, OrderState.EXTRACTED}:
            return 202
        return 200
    raise _orchestration_unavailable()


def _invalid_intake() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "INVALID_ORCHESTRATION_INTAKE",
            "message": "The orchestration intake request is invalid.",
        },
    )


def _idempotency_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "Idempotency key was already used for a different request.",
        },
    )


def _source_identity_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "SOURCE_IDENTITY_CONFLICT",
            "message": "The source document conflicts with the current order.",
        },
    )


def _orchestration_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "ORCHESTRATION_UNAVAILABLE",
            "message": "Orchestration intake is currently unavailable.",
        },
    )
