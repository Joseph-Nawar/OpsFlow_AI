"""Server-resolved development bearer authentication and Phase 6 capabilities."""

import hmac

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from opsflow.application.errors import ForbiddenError, UnauthenticatedError
from opsflow.domain import OrderState
from opsflow.review.contracts import OperatorContext, OperatorRole
from opsflow.settings import DevelopmentOperatorConfig

_bearer_security = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_security)


def resolve_operator_token(
    token: str,
    configured: tuple[DevelopmentOperatorConfig, ...],
) -> OperatorContext:
    """Resolve a bearer credential to only its server-configured identity and role."""

    if type(token) is not str or not token:
        raise UnauthenticatedError
    match: DevelopmentOperatorConfig | None = None
    supplied_bytes = token.encode("utf-8")
    for operator in configured:
        configured_bytes = operator.token.get_secret_value().encode("utf-8")
        if hmac.compare_digest(supplied_bytes, configured_bytes):
            match = operator
    if match is None:
        raise UnauthenticatedError
    return OperatorContext(actor=match.actor, role=match.role)


def get_operator_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> OperatorContext:
    """FastAPI dependency that never accepts browser actor or role claims."""

    if credentials is None:
        raise UnauthenticatedError
    configured = request.app.state.review_dev_operators
    return resolve_operator_token(credentials.credentials, configured)


def require_view_access(context: OperatorContext) -> None:
    """Require a recognized server-resolved Phase 6 operator context."""

    if not isinstance(context, OperatorContext) or not isinstance(context.role, OperatorRole):
        raise ForbiddenError


def require_reviewer(context: OperatorContext) -> None:
    """Require the reviewer role for review corrections and retry."""

    require_view_access(context)
    if context.role is not OperatorRole.REVIEWER:
        raise ForbiddenError


def require_approval(context: OperatorContext, *, high_value: bool) -> None:
    """Require ordinary or elevated approval capability for the warning state."""

    require_view_access(context)
    if context.role is OperatorRole.ELEVATED_APPROVER:
        return
    if context.role is OperatorRole.APPROVER and high_value is False:
        return
    raise ForbiddenError


def require_rejection(context: OperatorContext, state: OrderState) -> None:
    """Require the role/state pair authorized by the fixed Phase 6 matrix."""

    require_view_access(context)
    if context.role is OperatorRole.REVIEWER and state is OrderState.NEEDS_REVIEW:
        return
    if context.role in (OperatorRole.APPROVER, OperatorRole.ELEVATED_APPROVER) and (
        state is OrderState.READY_FOR_APPROVAL
    ):
        return
    raise ForbiddenError


def require_retry(context: OperatorContext) -> None:
    """Require reviewer capability for retry requests."""

    require_reviewer(context)
