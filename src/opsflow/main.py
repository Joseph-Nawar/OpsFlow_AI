"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from opsflow.api.notifications import router as notifications_router
from opsflow.api.orchestration import router as orchestration_router
from opsflow.api.orders import router as orders_router
from opsflow.api.review import router as review_router
from opsflow.application.errors import (
    ForbiddenError,
    OrchestrationUnauthenticatedError,
    UnauthenticatedError,
)
from opsflow.application.orchestration import execute_orchestration_intake
from opsflow.database import create_engine, create_sessionmaker, database_is_available
from opsflow.orchestration.composition import build_orchestration_runtime
from opsflow.orchestration.contracts import (
    OrchestrationIntakeCommand,
    OrchestrationIntakeHandler,
    OrchestrationIntakeResult,
)
from opsflow.review.composition import build_demo_review_runtime
from opsflow.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Dispose the application engine when the process shuts down."""

    try:
        yield
    finally:
        engine = cast(AsyncEngine, app.state.database_engine)
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application with environment-driven database settings."""

    resolved_settings = settings or get_settings()
    engine = create_engine(resolved_settings)
    app = FastAPI(title="OpsFlow AI", lifespan=lifespan)
    app.state.database_engine = engine
    app.state.database_sessionmaker = create_sessionmaker(engine)
    review_runtime = build_demo_review_runtime()
    app.state.review_runtime = review_runtime
    orchestration_runtime = build_orchestration_runtime(
        resolved_settings,
        review_runtime=review_runtime,
    )
    app.state.orchestration_runtime = orchestration_runtime
    app.state.review_dev_operators = resolved_settings.review_dev_operators
    app.state.orchestration_token = resolved_settings.orchestration_token

    async def orchestration_intake_handler(
        session: AsyncSession,
        command: OrchestrationIntakeCommand,
        actor: str,
        recorded_at: datetime,
    ) -> OrchestrationIntakeResult:
        return await execute_orchestration_intake(
            session,
            command,
            orchestration_runtime,
            actor,
            recorded_at,
        )

    typed_handler: OrchestrationIntakeHandler = orchestration_intake_handler
    app.state.orchestration_intake_handler = typed_handler
    app.include_router(orders_router)
    app.include_router(review_router)
    app.include_router(orchestration_router)
    app.include_router(notifications_router)

    @app.exception_handler(UnauthenticatedError)
    async def unauthenticated_error_handler(
        request: Request, error: UnauthenticatedError
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={
                "detail": {
                    "code": "UNAUTHENTICATED",
                    "message": "Development operator authentication is required.",
                }
            },
        )

    @app.exception_handler(OrchestrationUnauthenticatedError)
    async def orchestration_unauthenticated_error_handler(
        request: Request, error: OrchestrationUnauthenticatedError
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={
                "detail": {
                    "code": "ORCHESTRATION_UNAUTHENTICATED",
                    "message": "Orchestration service authentication is required.",
                }
            },
        )

    @app.exception_handler(ForbiddenError)
    async def forbidden_error_handler(request: Request, error: ForbiddenError) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "code": "FORBIDDEN",
                    "message": "The operator is not permitted.",
                }
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return the process liveness response without dependency checks."""

        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Return dependency readiness without exposing database details."""

        engine = cast(AsyncEngine, request.app.state.database_engine)
        if await database_is_available(engine):
            return JSONResponse(
                status_code=200,
                content={"status": "ready", "checks": {"database": "ok"}},
            )
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": {"database": "unavailable"}},
        )

    return app


app = create_app()
