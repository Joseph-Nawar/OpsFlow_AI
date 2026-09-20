"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from opsflow.api.orders import router as orders_router
from opsflow.api.review import router as review_router
from opsflow.application.errors import ForbiddenError, UnauthenticatedError
from opsflow.database import create_engine, create_sessionmaker, database_is_available
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
    app.state.review_runtime = build_demo_review_runtime()
    app.state.review_dev_operators = resolved_settings.review_dev_operators
    app.include_router(orders_router)
    app.include_router(review_router)

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
