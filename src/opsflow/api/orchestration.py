"""Authenticated HTTP boundary for orchestration intake and order synchronization."""

import time
from collections.abc import Callable, Coroutine
from contextlib import suppress
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
from sqlalchemy.exc import SQLAlchemyError

from opsflow.application.errors import (
    IdempotencyConflictError,
    SourceIdentityMismatchError,
    SourceOwnershipError,
)
from opsflow.application.orchestration import OrchestrationUnavailableError
from opsflow.application.order_sync import (
    OrderSyncExecutionDeadlineExceeded,
    OrderSyncNotFoundError,
    OrderSyncStepPreconditionError,
    execute_next_order_sync,
)
from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from opsflow.domain import OrderState
from opsflow.observability.runtime import current_observability, duration_ms
from opsflow.orchestration.auth import get_orchestration_actor
from opsflow.orchestration.contracts import (
    IntakeExecution,
    OrchestrationIntakeHandler,
    OrchestrationIntakeResult,
)
from opsflow.orchestration.transport import build_intake_command
from opsflow.order_sync.contracts import OrderSyncStepExecutor

from .orchestration_schemas import OrchestrationIntakeResponse, OrderSyncExecutionResponse
from .orders import SessionDependency

_PHASE7_COMPLETED_STATES = frozenset(
    {
        OrderState.NEEDS_REVIEW,
        OrderState.READY_FOR_APPROVAL,
        OrderState.FAILED_RETRYABLE,
        OrderState.FAILED_FINAL,
    }
)


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
    document_type: Annotated[str, Form(..., max_length=32)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    actor: OrchestrationActorDependency,
    session: SessionDependency,
    response: Response,
    message_id: Annotated[str | None, Form(max_length=256)] = None,
    source_system: Annotated[str | None, Form(max_length=32)] = None,
) -> OrchestrationIntakeResponse:
    """Accept one authenticated document and delegate to orchestration intake."""

    started_ns = time.perf_counter_ns()
    try:
        command = await build_intake_command(
            document,
            document_type,
            message_id,
            idempotency_key,
            source_system=source_system,
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
    except OrchestrationUnavailableError as error:
        raise _orchestration_unavailable() from error
    except DocumentValidationError as error:
        raise _invalid_intake() from error
    except IdempotencyConflictError as error:
        raise _idempotency_conflict() from error
    except (SourceIdentityMismatchError, SourceOwnershipError) as error:
        raise _source_identity_conflict() from error

    response.status_code = _status_for_result(result)
    observer = current_observability()
    if observer is not None:
        with suppress(Exception):
            observer.intake_outcome(
                state=result.state.value,
                duration_ms=duration_ms(started_ns),
                order_id=str(result.order_id),
                retry_outcome=(
                    "DELAYED_RECOVERY"
                    if result.retry_after_seconds is not None
                    else result.execution.value
                ),
            )
    return OrchestrationIntakeResponse(
        order_id=result.order_id,
        state=result.state,
        failure_origin=result.failure_origin,
        idempotent_replay=result.idempotent_replay,
        retry_after_seconds=result.retry_after_seconds,
    )


@router.post(
    "/order-sync/execute-next",
    response_model=OrderSyncExecutionResponse,
    responses={
        401: {"description": "Orchestration service authentication is required."},
        503: {"description": "Order synchronization is unavailable."},
    },
)
async def execute_next_order_sync_endpoint(
    request: Request,
    actor: OrchestrationActorDependency,
    session: SessionDependency,
) -> OrderSyncExecutionResponse:
    """Execute one durable order-sync progression through the configured backend seam."""

    del actor
    executor = cast(OrderSyncStepExecutor | None, request.app.state.order_sync_step_executor)
    if executor is None:
        raise _order_sync_unavailable()
    try:
        result = await execute_next_order_sync(session, executor)
    except (
        SQLAlchemyError,
        OrderSyncExecutionDeadlineExceeded,
        OrderSyncNotFoundError,
        OrderSyncStepPreconditionError,
    ) as error:
        raise _order_sync_unavailable() from error
    return OrderSyncExecutionResponse(
        result=result.kind,
        order_id=result.order_id,
        state=result.state,
    )


def _status_for_result(result: OrchestrationIntakeResult) -> int:
    if result.execution is IntakeExecution.STANDING_DOWN:
        if result.state in {OrderState.PROCESSING, OrderState.EXTRACTED}:
            return 202
        return 200
    if result.execution is IntakeExecution.COMPLETED:
        if result.state not in _PHASE7_COMPLETED_STATES:
            raise _orchestration_unavailable()
        return 200 if result.idempotent_replay else 201
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


def _order_sync_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "ORDER_SYNC_UNAVAILABLE",
            "message": "Order synchronization is currently unavailable.",
        },
    )
