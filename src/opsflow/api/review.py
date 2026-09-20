"""Narrow transport routes for Phase 6 human-review reads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from opsflow.application.errors import (
    BusinessDataProviderError,
    ForbiddenError,
    InvalidTrustedDataError,
    OrderNotFoundError,
    ReviewCaseUnavailableError,
    ReviewDraftUnavailableError,
)
from opsflow.application.review_reads import (
    get_current_reference_data,
    get_review_detail,
    list_review_orders,
)
from opsflow.domain import OrderState
from opsflow.review import OperatorContext
from opsflow.review.auth import get_operator_context

from .orders import SessionDependency
from .review_schemas import (
    ReviewDetailResponse,
    ReviewQueueResponse,
    ReviewReferenceDataResponse,
    reference_data_response,
    review_detail_response,
    review_queue_response,
)

router = APIRouter(prefix="/v1/review/orders", tags=["human review"])
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
