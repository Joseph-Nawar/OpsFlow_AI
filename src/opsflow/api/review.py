"""Narrow transport routes for Phase 6 human-review reads and commands."""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from opsflow.application.errors import (
    BusinessDataProviderError,
    ForbiddenError,
    InvalidRejectionReasonError,
    InvalidReviewStateError,
    InvalidTrustedDataError,
    NoReviewChangesError,
    OrderNotFoundError,
    ReviewCaseUnavailableError,
    ReviewDraftUnavailableError,
    ReviewPersistenceConflictError,
    ReviewPreconditionFailedError,
    ReviewPreconditionRequiredError,
    ValidationFactsChangedError,
)
from opsflow.application.review_commands import (
    approve_order,
    reject_order,
    retry_order,
)
from opsflow.application.review_reads import (
    get_current_reference_data,
    get_review_detail,
    list_review_orders,
)
from opsflow.application.review_revalidation import save_and_revalidate
from opsflow.domain import DomainValidationError, OrderState
from opsflow.review import OperatorContext
from opsflow.review.auth import get_operator_context

from .orders import SessionDependency
from .review_schemas import (
    ReviewCommandResponse,
    ReviewDetailResponse,
    ReviewDraftRequest,
    ReviewQueueResponse,
    ReviewReferenceDataResponse,
    ReviewRejectRequest,
    reference_data_response,
    review_command_response,
    review_detail_response,
    review_queue_response,
)


class _ReviewRoute(APIRoute):
    """Keep review mutation transport errors in a bounded non-echoing shape."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()
        is_draft_command = self.path == "/v1/review/orders/{order_id}/draft"
        is_review_command = self.path in {
            "/v1/review/orders/{order_id}/approve",
            "/v1/review/orders/{order_id}/reject",
            "/v1/review/orders/{order_id}/retry",
        }

        async def handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError:
                if is_draft_command:
                    return JSONResponse(
                        status_code=422,
                        content={
                            "detail": {
                                "code": "INVALID_REVIEW_DRAFT",
                                "message": "The submitted review draft is invalid.",
                            }
                        },
                    )
                if not is_review_command:
                    raise
                code = (
                    "INVALID_REJECTION_REQUEST"
                    if self.path.endswith("/reject")
                    else "INVALID_COMMAND_REQUEST"
                )
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": code,
                            "message": "The review command request is invalid.",
                        }
                    },
                )

        return handler


router = APIRouter(prefix="/v1/review/orders", tags=["human review"], route_class=_ReviewRoute)
OperatorDependency = Annotated[OperatorContext, Depends(get_operator_context)]
_COMMAND_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "A configured development bearer credential is required."},
    403: {"description": "The resolved operator lacks this command capability."},
    404: {"description": "The order was not found."},
    409: {"description": "The command is invalid for current persisted state."},
    412: {"description": "If-Match is malformed or no longer current."},
    422: {"description": "The command request or rejection reason is invalid."},
    428: {"description": "A strong If-Match review validator is required."},
}
_IF_MATCH_OPENAPI_EXTRA = {
    "parameters": [
        {
            "name": "If-Match",
            "in": "header",
            "required": True,
            "description": "Required strong review ETag.",
            "schema": {"type": "string"},
        }
    ]
}
_IF_MATCH_HEADER = Header(
    alias="If-Match",
    description="Required strong review ETag; missing values return HTTP 428.",
    include_in_schema=False,
)


@router.get("", response_model=ReviewQueueResponse)
async def list_review_orders_endpoint(
    session: SessionDependency,
    operator: OperatorDependency,
    states: Annotated[list[OrderState] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewQueueResponse:
    """Return an authorized bounded review queue in deterministic order."""

    try:
        page = await list_review_orders(
            session,
            tuple(states) if states is not None else None,
            limit,
            offset,
            operator,
        )
    except ForbiddenError as error:
        raise _forbidden() from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_REVIEW_QUEUE_FILTER",
                "message": "Review queue filters are invalid.",
            },
        ) from error
    return review_queue_response(page)


@router.get("/{order_id}", response_model=ReviewDetailResponse)
async def get_review_detail_endpoint(
    order_id: UUID,
    response: Response,
    session: SessionDependency,
    operator: OperatorDependency,
) -> ReviewDetailResponse:
    """Return stable review detail with a matching body/header strong ETag."""

    try:
        detail = await get_review_detail(session, order_id, operator)
    except OrderNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ORDER_NOT_FOUND", "message": "Order was not found."},
        ) from error
    except ReviewCaseUnavailableError as error:
        raise _review_case_unavailable() from error
    except ForbiddenError as error:
        raise _forbidden() from error
    response.headers["ETag"] = detail.etag
    return review_detail_response(detail)


@router.get("/{order_id}/reference-data", response_model=ReviewReferenceDataResponse)
async def get_review_reference_data_endpoint(
    order_id: UUID,
    request: Request,
    session: SessionDependency,
    operator: OperatorDependency,
) -> ReviewReferenceDataResponse:
    """Return a separate volatile lookup of current trusted reference data."""

    provider = request.app.state.review_runtime.provider
    try:
        data = await get_current_reference_data(session, order_id, operator, provider)
    except OrderNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ORDER_NOT_FOUND", "message": "Order was not found."},
        ) from error
    except ReviewDraftUnavailableError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REVIEW_DRAFT_UNAVAILABLE",
                "message": "No effective review draft is available.",
            },
        ) from error
    except ReviewCaseUnavailableError as error:
        raise _review_case_unavailable() from error
    except InvalidTrustedDataError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "REFERENCE_DATA_INVALID",
                "message": "Current trusted reference data is unavailable.",
            },
        ) from error
    except BusinessDataProviderError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "REFERENCE_DATA_UNAVAILABLE",
                "message": "Current trusted reference data is unavailable.",
            },
        ) from error
    except ForbiddenError as error:
        raise _forbidden() from error
    return reference_data_response(data)


@router.put(
    "/{order_id}/draft",
    response_model=ReviewDetailResponse,
    responses={
        412: {"description": "If-Match is malformed or no longer current."},
        428: {"description": "A strong If-Match review validator is required."},
    },
    openapi_extra={
        "parameters": [
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "description": "Required strong review ETag.",
                "schema": {"type": "string"},
            }
        ]
    },
)
async def save_review_draft_endpoint(
    order_id: UUID,
    body: ReviewDraftRequest,
    response: Response,
    session: SessionDependency,
    operator: OperatorDependency,
    request: Request,
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            description="Required strong review ETag; if omitted, the service returns HTTP 428.",
            include_in_schema=False,
        ),
    ] = None,
) -> ReviewDetailResponse:
    """Save a complete changed candidate and deterministically revalidate it."""

    runtime = request.app.state.review_runtime
    try:
        await save_and_revalidate(
            session,
            order_id,
            body.to_contract(),
            if_match,
            operator,
            runtime.provider,
            runtime.policy,
            runtime.date_provider,
            datetime.now(UTC),
        )
        detail = await get_review_detail(session, order_id, operator)
    except ReviewPreconditionRequiredError as error:
        raise HTTPException(
            status_code=428,
            detail={"code": "PRECONDITION_REQUIRED", "message": "If-Match is required."},
        ) from error
    except ReviewPreconditionFailedError as error:
        raise HTTPException(
            status_code=412,
            detail={"code": "PRECONDITION_FAILED", "message": "Review state changed."},
        ) from error
    except NoReviewChangesError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "NO_REVIEW_CHANGES", "message": "No review changes were submitted."},
        ) from error
    except InvalidReviewStateError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_REVIEW_STATE", "message": "Review action is unavailable."},
        ) from error
    except ReviewCaseUnavailableError as error:
        raise _review_case_unavailable() from error
    except OrderNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "ORDER_NOT_FOUND", "message": "Order was not found."},
        ) from error
    except ValidationFactsChangedError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VALIDATION_FACTS_CHANGED",
                "message": "Current order facts changed; review the case again.",
            },
        ) from error
    except ReviewPersistenceConflictError as error:
        raise _review_persistence_conflict() from error
    except InvalidTrustedDataError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "REFERENCE_DATA_INVALID",
                "message": "Current trusted reference data is unavailable.",
            },
        ) from error
    except BusinessDataProviderError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "REFERENCE_DATA_UNAVAILABLE",
                "message": "Current trusted reference data is unavailable.",
            },
        ) from error
    except DomainValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_REVIEW_DRAFT",
                "message": "The submitted review draft is invalid.",
            },
        ) from error

    response.headers["ETag"] = detail.etag
    return review_detail_response(detail)


@router.post(
    "/{order_id}/approve",
    response_model=ReviewCommandResponse,
    responses=_COMMAND_RESPONSES,
    openapi_extra=_IF_MATCH_OPENAPI_EXTRA,
)
async def approve_review_order_endpoint(
    order_id: UUID,
    request: Request,
    response: Response,
    session: SessionDependency,
    operator: OperatorDependency,
    if_match: Annotated[str | None, _IF_MATCH_HEADER] = None,
) -> ReviewCommandResponse:
    """Approve one eligible order without triggering synchronization."""

    await _require_empty_command_body(request)
    try:
        result = await approve_order(
            session,
            order_id,
            if_match,
            operator,
            datetime.now(UTC),
        )
    except (
        InvalidReviewStateError,
        OrderNotFoundError,
        ReviewPersistenceConflictError,
        ReviewPreconditionFailedError,
        ReviewPreconditionRequiredError,
        DomainValidationError,
    ) as error:
        raise _command_error(error) from error
    response.headers["ETag"] = result.etag
    return review_command_response(result)


@router.post(
    "/{order_id}/reject",
    response_model=ReviewCommandResponse,
    responses=_COMMAND_RESPONSES,
    openapi_extra=_IF_MATCH_OPENAPI_EXTRA,
)
async def reject_review_order_endpoint(
    order_id: UUID,
    body: ReviewRejectRequest,
    response: Response,
    session: SessionDependency,
    operator: OperatorDependency,
    if_match: Annotated[str | None, _IF_MATCH_HEADER] = None,
) -> ReviewCommandResponse:
    """Reject one eligible order with a bounded operator reason."""

    try:
        result = await reject_order(
            session,
            order_id,
            body.reason,
            if_match,
            operator,
            datetime.now(UTC),
        )
    except (
        InvalidRejectionReasonError,
        InvalidReviewStateError,
        OrderNotFoundError,
        ReviewPersistenceConflictError,
        ReviewPreconditionFailedError,
        ReviewPreconditionRequiredError,
        DomainValidationError,
    ) as error:
        raise _command_error(error) from error
    response.headers["ETag"] = result.etag
    return review_command_response(result)


@router.post(
    "/{order_id}/retry",
    response_model=ReviewCommandResponse,
    responses=_COMMAND_RESPONSES,
    openapi_extra=_IF_MATCH_OPENAPI_EXTRA,
)
async def retry_review_order_endpoint(
    order_id: UUID,
    request: Request,
    response: Response,
    session: SessionDependency,
    operator: OperatorDependency,
    if_match: Annotated[str | None, _IF_MATCH_HEADER] = None,
) -> ReviewCommandResponse:
    """Clear an eligible retryable failure without resuming processing."""

    await _require_empty_command_body(request)
    try:
        result = await retry_order(
            session,
            order_id,
            if_match,
            operator,
            datetime.now(UTC),
        )
    except (
        InvalidReviewStateError,
        OrderNotFoundError,
        ReviewPersistenceConflictError,
        ReviewPreconditionFailedError,
        ReviewPreconditionRequiredError,
        DomainValidationError,
    ) as error:
        raise _command_error(error) from error
    response.headers["ETag"] = result.etag
    return review_command_response(result)


async def _require_empty_command_body(request: Request) -> None:
    if await request.body():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_COMMAND_REQUEST",
                "message": "This review command does not accept a request body.",
            },
        )


def _command_error(error: Exception) -> HTTPException:
    if isinstance(error, ReviewPreconditionRequiredError):
        return HTTPException(
            status_code=428,
            detail={"code": "PRECONDITION_REQUIRED", "message": "If-Match is required."},
        )
    if isinstance(error, ReviewPreconditionFailedError):
        return HTTPException(
            status_code=412,
            detail={"code": "PRECONDITION_FAILED", "message": "Review state changed."},
        )
    if isinstance(error, OrderNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "ORDER_NOT_FOUND", "message": "Order was not found."},
        )
    if isinstance(error, InvalidRejectionReasonError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_REJECTION_REASON",
                "message": "A nonblank rejection reason of at most 500 characters is required.",
            },
        )
    if isinstance(error, InvalidReviewStateError):
        return HTTPException(
            status_code=409,
            detail={"code": "INVALID_REVIEW_STATE", "message": "Review action is unavailable."},
        )
    if isinstance(error, ReviewPersistenceConflictError):
        return _review_persistence_conflict()
    return HTTPException(
        status_code=409,
        detail={"code": "REVIEW_CASE_UNAVAILABLE", "message": "Review case is unavailable."},
    )


def _review_case_unavailable() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "REVIEW_CASE_UNAVAILABLE",
            "message": "Review case is unavailable.",
        },
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "FORBIDDEN", "message": "The operator is not permitted."},
    )


def _review_persistence_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "REVIEW_PERSISTENCE_CONFLICT",
            "message": "Review state changed; refresh the case and try again.",
        },
    )
