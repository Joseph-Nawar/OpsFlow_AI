"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from opsflow.api.notifications import router as notifications_router
from opsflow.api.operations import router as operations_router
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
from opsflow.http_limits import RequestBodyLimitMiddleware
from opsflow.hubspot import HubSpotCRMAdapter
from opsflow.observability.middleware import RequestCorrelationMiddleware
from opsflow.observability.runtime import Observability
from opsflow.odoo import OdooERPAdapter
from opsflow.orchestration.composition import build_orchestration_runtime
from opsflow.orchestration.contracts import (
    OrchestrationIntakeCommand,
    OrchestrationIntakeHandler,
    OrchestrationIntakeResult,
)
from opsflow.order_sync.executor import Phase9OrderSyncExecutor
from opsflow.review.composition import build_demo_review_runtime
from opsflow.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Dispose the application engine when the process shuts down."""

    try:
        yield
    finally:
        odoo_adapter = getattr(app.state, "odoo_adapter", None)
        if odoo_adapter is not None:
            await odoo_adapter.aclose()
        hubspot_adapter = getattr(app.state, "hubspot_adapter", None)
        if hubspot_adapter is not None:
            await hubspot_adapter.aclose()
        engine = cast(AsyncEngine, app.state.database_engine)
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application with environment-driven database settings."""

    resolved_settings = settings or get_settings()
    engine = create_engine(resolved_settings)
    app = FastAPI(title="OpsFlow AI", lifespan=lifespan)
    app.state.observability = Observability(_integration_configuration(resolved_settings))
    app.state.database_engine = engine
    app.state.database_sessionmaker = create_sessionmaker(engine)
    review_runtime = build_demo_review_runtime()
    odoo_adapter: OdooERPAdapter | None = None
    if resolved_settings.odoo_base_url is not None:
        odoo_adapter = OdooERPAdapter(
            resolved_settings,
            sessionmaker=app.state.database_sessionmaker,
            policy=review_runtime.policy,
        )
        review_runtime = replace(review_runtime, provider=odoo_adapter)
    hubspot_adapter: HubSpotCRMAdapter | None = None
    order_sync_step_executor: Phase9OrderSyncExecutor | None = None
    hubspot_settings_complete = all(
        value is not None
        for value in (
            resolved_settings.hubspot_service_key,
            resolved_settings.hubspot_pipeline_id,
            resolved_settings.hubspot_initial_stage_id,
            resolved_settings.hubspot_portal_currency,
            resolved_settings.hubspot_expected_portal_id,
        )
    )
    if odoo_adapter is not None and hubspot_settings_complete:
        hubspot_adapter = HubSpotCRMAdapter(
            resolved_settings,
            sessionmaker=app.state.database_sessionmaker,
            business_data_provider=odoo_adapter,
        )
        order_sync_step_executor = Phase9OrderSyncExecutor(
            odoo=odoo_adapter,
            hubspot=hubspot_adapter,
        )
    app.state.review_runtime = review_runtime
    orchestration_runtime = build_orchestration_runtime(
        resolved_settings,
        review_runtime=review_runtime,
    )
    app.state.orchestration_runtime = orchestration_runtime
    app.state.review_dev_operators = resolved_settings.review_dev_operators
    app.state.orchestration_token = resolved_settings.orchestration_token
    app.state.odoo_adapter = odoo_adapter
    app.state.hubspot_adapter = hubspot_adapter
    # Execute-next requires both complete provider adapters and uses the same M9B seam.
    app.state.order_sync_step_executor = order_sync_step_executor

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
    app.include_router(operations_router)

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

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "INVALID_REQUEST",
                    "message": "The request is invalid.",
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

    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(RequestCorrelationMiddleware, observability=app.state.observability)
    return app


def _integration_configuration(settings: Settings) -> dict[str, str]:
    """Resolve configuration state without attempting any external connection."""

    gemini_complete = all(
        value is not None and (not isinstance(value, str) or bool(value.strip()))
        for value in (
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_timeout_seconds,
        )
    )
    odoo_complete = all(
        value is not None
        for value in (
            settings.odoo_base_url,
            settings.odoo_database,
            settings.odoo_api_key,
            settings.odoo_company_id,
            settings.odoo_warehouse_id,
            settings.odoo_pricelist_id,
        )
    )
    hubspot_complete = all(
        value is not None
        for value in (
            settings.hubspot_service_key,
            settings.hubspot_pipeline_id,
            settings.hubspot_initial_stage_id,
            settings.hubspot_portal_currency,
            settings.hubspot_expected_portal_id,
        )
    )
    return {
        "gemini": "CONFIGURED" if gemini_complete else "UNCONFIGURED",
        "odoo": "CONFIGURED" if odoo_complete else "UNCONFIGURED",
        "hubspot": "CONFIGURED" if hubspot_complete else "UNCONFIGURED",
        "gmail": "EXTERNALLY_MANAGED",
        "slack": "EXTERNALLY_MANAGED",
        "n8n": "EXTERNALLY_MANAGED",
    }


app = create_app()
