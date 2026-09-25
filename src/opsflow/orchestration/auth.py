"""Fixed-identity bearer authentication for the n8n orchestration service."""

import hmac
from typing import Final

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from opsflow.application.errors import OrchestrationUnauthenticatedError

ORCHESTRATION_ACTOR: Final[str] = "orchestration:n8n"

_bearer_security = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_security)


def resolve_orchestration_token(
    token: str,
    configured: SecretStr | None,
) -> str:
    """Resolve one configured bearer secret to the server-owned actor."""

    if type(token) is not str or not token.strip() or configured is None:
        raise OrchestrationUnauthenticatedError

    configured_value = configured.get_secret_value()
    if not configured_value.strip():
        raise OrchestrationUnauthenticatedError

    supplied_bytes = token.encode("utf-8")
    configured_bytes = configured_value.encode("utf-8")
    if not hmac.compare_digest(supplied_bytes, configured_bytes):
        raise OrchestrationUnauthenticatedError
    return ORCHESTRATION_ACTOR


def get_orchestration_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> str:
    """Authenticate the bearer credential using only server-owned configuration."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise OrchestrationUnauthenticatedError

    configured = getattr(request.app.state, "orchestration_token", None)
    return resolve_orchestration_token(credentials.credentials, configured)
