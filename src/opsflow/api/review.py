"""Narrow transport routes for Phase 6 human-review reads."""

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
    ReviewDetailResponse,
    ReviewDraftRequest,
    ReviewQueueResponse,
    ReviewReferenceDataResponse,
    reference_data_response,
    review_detail_response,
    review_queue_response,
)


class _ReviewRoute(APIRoute):
    """Keep draft transport validation errors in the bounded review error shape."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()
        is_draft_command = self.path == "/v1/review/orders/{order_id}/draft"

        async def handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError:
                if not is_draft_command:
                    raise
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": "INVALID_REVIEW_DRAFT",
                            "message": "The submitted review draft is invalid.",
                        }
                    },
                )

        return handler


router = APIRouter(prefix="/v1/review/orders", tags=["human review"], route_class=_ReviewRoute)
OperatorDependency = Annotated[OperatorContext, Depends(get_operator_context)]


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
