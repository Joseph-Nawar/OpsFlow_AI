"""Human-view-only operational diagnostics endpoints."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from opsflow.observability.runtime import Observability
from opsflow.review import OperatorContext
from opsflow.review.auth import get_operator_context, require_view_access

router = APIRouter(prefix="/v1/operations", tags=["operations"])
OperatorDependency = Annotated[OperatorContext, Depends(get_operator_context)]


def require_operations_view_access(context: OperatorDependency) -> OperatorContext:
    """Require the existing server-resolved human development view capability."""

    require_view_access(context)
    return context


ViewOperatorDependency = Annotated[OperatorContext, Depends(require_operations_view_access)]


@router.get("/metrics")
async def metrics_endpoint(
    request: Request,
    operator: ViewOperatorDependency,
) -> dict[str, object]:
    """Return a bounded process-local metrics snapshot."""

    del operator
    observability = cast(Observability, request.app.state.observability)
    return observability.metrics.snapshot()


@router.get("/integrations")
async def integrations_endpoint(
    request: Request,
    operator: ViewOperatorDependency,
) -> dict[str, object]:
    """Return passive last-observed integration outcomes without probing providers."""

    del operator
    observability = cast(Observability, request.app.state.observability)
    return {"integrations": observability.integrations.snapshot()}


__all__ = ["router"]
