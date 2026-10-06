"""Core order HTTP routes and transport-level error translation."""

from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opsflow.application.errors import IdempotencyConflictError, OrderNotFoundError
from opsflow.application.orders import (
    create_order as application_create_order,
)
from opsflow.application.orders import (
    get_order as application_get_order,
)
from opsflow.application.orders import (
    get_order_audit as application_get_order_audit,
)
from opsflow.application.orders import (
    list_orders as application_list_orders,
)
from opsflow.domain import DomainValidationError
from opsflow.orchestration.auth import get_orchestration_actor
from opsflow.review import OperatorContext
from opsflow.review.auth import get_operator_context, require_view_access

from .schemas import (
    AuditListResponse,
    OrderCreateRequest,
    OrderDetailResponse,
    OrderListResponse,
    audit_event_response,
    order_detail_response,
    order_summary_response,
    to_create_order_input,
)

router = APIRouter(prefix="/v1/orders", tags=["orders"])


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session from the app's shared factory."""

    session_factory = cast(
        async_sessionmaker[AsyncSession], request.app.state.database_sessionmaker
    )
    async with session_factory() as session:
        yield session


SessionDependency = Annotated[AsyncSession, Depends(get_session)]
OperatorDependency = Annotated[OperatorContext, Depends(get_operator_context)]
OrchestrationActorDependency = Annotated[str, Depends(get_orchestration_actor)]


def require_order_view_access(context: OperatorDependency) -> OperatorContext:
    """Apply the existing server-resolved human view capability to core reads."""

    require_view_access(context)
    return context


ViewOperatorDependency = Annotated[OperatorContext, Depends(require_order_view_access)]


@router.post("", response_model=OrderDetailResponse, status_code=201)
async def create_order_endpoint(
    request: OrderCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    actor: OrchestrationActorDependency,
    session: SessionDependency,
) -> OrderDetailResponse:
    """Create or replay one received order through application orchestration."""

    del actor
    if not idempotency_key.strip():
        raise HTTPException(status_code=422, detail="Idempotency-Key must not be blank")
    try:
        result = await application_create_order(
            session,
            to_create_order_input(request),
            idempotency_key,
        )
    except IdempotencyConflictError as error:
        raise _idempotency_conflict() from error
    except DomainValidationError as error:
        raise _domain_validation(error) from error
    return order_detail_response(result)


@router.get("", response_model=OrderListResponse)
async def list_order_endpoint(
    session: SessionDependency,
    operator: ViewOperatorDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderListResponse:
    """Return deterministic lightweight order summaries."""

    del operator
    items, total = await application_list_orders(session, limit, offset)
    return OrderListResponse(
        items=[order_summary_response(item) for item in items],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get("/{order_id}", response_model=OrderDetailResponse)
async def get_order_endpoint(
    order_id: UUID,
    session: SessionDependency,
    operator: ViewOperatorDependency,
) -> OrderDetailResponse:
    """Return one detailed order or a safe not-found response."""

    del operator
    try:
        result = await application_get_order(session, order_id)
    except OrderNotFoundError as error:
        raise _order_not_found() from error
    return order_detail_response(result)


@router.get("/{order_id}/audit", response_model=AuditListResponse)
async def get_order_audit_endpoint(
    order_id: UUID,
    session: SessionDependency,
    operator: ViewOperatorDependency,
) -> AuditListResponse:
    """Return the separate deterministic audit history for one order."""

    del operator
    try:
        events = await application_get_order_audit(session, order_id)
    except OrderNotFoundError as error:
        raise _order_not_found() from error
    return AuditListResponse(items=[audit_event_response(event) for event in events])


def _order_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "ORDER_NOT_FOUND", "message": "Order was not found."},
    )


def _idempotency_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "Idempotency key was already used for a different request.",
        },
    )


def _domain_validation(error: DomainValidationError) -> HTTPException:
    del error
    return HTTPException(
        status_code=422,
        detail={"code": "INVALID_ORDER", "message": "The submitted order is invalid."},
    )
