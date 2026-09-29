"""Authenticated, bounded HTTP transport for durable notification delivery."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from opsflow.notifications.contracts import NotificationOutcome
from opsflow.notifications.service import (
    NotificationNotFoundError,
    StaleNotificationClaimError,
    claim_next_notification,
    record_notification_outcome,
)
from opsflow.orchestration.auth import get_orchestration_actor

from .notification_schemas import (
    NotificationClaimResponse,
    NotificationOutcomeRequest,
    NotificationOutcomeResponse,
)
from .orders import SessionDependency


class _NotificationRoute(APIRoute):
    """Hide request values and provider diagnostics from validation responses."""

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
                            "code": "INVALID_NOTIFICATION_REQUEST",
                            "message": "The notification request is invalid.",
                        }
                    },
                )

        return handler


router = APIRouter(
    prefix="/v1/integrations/notifications",
    tags=["notification delivery"],
    route_class=_NotificationRoute,
)
OrchestrationActorDependency = Annotated[str, Depends(get_orchestration_actor)]
_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "A configured orchestration service bearer is required."},
    422: {"description": "The bounded notification request is invalid."},
    503: {"description": "Notification persistence is temporarily unavailable."},
}


@router.post(
    "/claim",
    response_model=NotificationClaimResponse,
    responses={**_RESPONSES, 204: {"description": "No notification is currently eligible."}},
)
async def claim_notification_endpoint(
    actor: OrchestrationActorDependency,
    session: SessionDependency,
) -> NotificationClaimResponse | Response:
    """Commit and return one eligible delivery claim or a bodyless 204."""

    del actor
    try:
        claim = await claim_next_notification(session)
    except SQLAlchemyError as error:
        raise _unavailable() from error
    if claim is None:
        return Response(status_code=204)
    return NotificationClaimResponse(
        notification_id=claim.notification_id,
        channel=claim.channel,
        kind=claim.kind,
        payload=claim.payload,
        attempt_number=claim.attempt_number,
        claim_token=claim.claim_token,
        claim_expires_at=claim.claim_expires_at,
    )


@router.post(
    "/{notification_id}/outcome",
    response_model=NotificationOutcomeResponse,
    responses={
        **_RESPONSES,
        404: {"description": "Notification ID was not found."},
        409: {"description": "The notification claim is stale."},
    },
)
async def record_notification_outcome_endpoint(
    notification_id: UUID,
    body: NotificationOutcomeRequest,
    actor: OrchestrationActorDependency,
    session: SessionDependency,
) -> NotificationOutcomeResponse:
    """Persist one result for the current unexpired claim generation."""

    del actor
    outcome = NotificationOutcome(
        claim_token=body.claim_token,
        kind=body.outcome,
        provider_reference=body.provider_reference,
        failure_code=body.failure_code,
        retry_after_seconds=body.retry_after_seconds,
    )
    try:
        result = await record_notification_outcome(session, notification_id, outcome)
    except NotificationNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOTIFICATION_NOT_FOUND", "message": "Notification was not found."},
        ) from error
    except StaleNotificationClaimError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "STALE_NOTIFICATION_CLAIM",
                "message": "Notification claim is no longer current.",
            },
        ) from error
    except SQLAlchemyError as error:
        raise _unavailable() from error
    return NotificationOutcomeResponse(
        notification_id=result.notification_id,
        status=result.status,
        attempt_count=result.attempt_count,
        next_attempt_at=result.next_attempt_at,
        provider_reference=result.provider_reference,
        failure_code=result.last_failure_code,
    )


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "NOTIFICATION_UNAVAILABLE",
            "message": "Notification persistence is temporarily unavailable.",
        },
    )
