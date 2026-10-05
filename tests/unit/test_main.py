"""Application composition for optional Phase 9 Odoo provider settings."""

import asyncio

import pytest

from opsflow.main import create_app
from opsflow.odoo import OdooERPAdapter
from opsflow.review.composition import ReviewRuntime
from opsflow.settings import Settings


def _odoo_settings() -> Settings:
    return Settings(
        _env_file=None,
        odoo_base_url="http://odoo.test",
        odoo_database="opsflow_test",
        odoo_api_key="test-api-key",
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
    )


def _combined_settings() -> Settings:
    return Settings(
        _env_file=None,
        odoo_base_url="http://odoo.test",
        odoo_database="opsflow_test",
        odoo_api_key="test-api-key",
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
        hubspot_service_key="test-hubspot-key",
        hubspot_pipeline_id="default",
        hubspot_initial_stage_id="appointmentscheduled",
        hubspot_portal_currency="USD",
        hubspot_expected_portal_id=149461984,
    )


def test_missing_odoo_configuration_leaves_executor_unset() -> None:
    app = create_app(Settings(_env_file=None))
    try:
        assert app.state.order_sync_step_executor is None
        assert app.state.odoo_adapter is None
    finally:
        asyncio.run(app.state.database_engine.dispose())


def test_odoo_configuration_keeps_review_provider_but_disables_sync_executor() -> None:
    app = create_app(_odoo_settings())
    adapter = app.state.odoo_adapter
    try:
        assert isinstance(adapter, OdooERPAdapter)
        assert app.state.order_sync_step_executor is None
        assert isinstance(app.state.review_runtime, ReviewRuntime)
        assert app.state.review_runtime.provider is adapter
    finally:

        async def close() -> None:
            await adapter.aclose()
            await app.state.database_engine.dispose()

        asyncio.run(close())


def test_complete_provider_configuration_composes_fixed_phase9_executor() -> None:
    from opsflow.hubspot import HubSpotCRMAdapter
    from opsflow.order_sync.executor import Phase9OrderSyncExecutor

    app = create_app(_combined_settings())
    odoo_adapter = app.state.odoo_adapter
    hubspot_adapter = app.state.hubspot_adapter
    try:
        assert isinstance(odoo_adapter, OdooERPAdapter)
        assert isinstance(hubspot_adapter, HubSpotCRMAdapter)
        assert isinstance(app.state.order_sync_step_executor, Phase9OrderSyncExecutor)
        assert isinstance(app.state.review_runtime, ReviewRuntime)
        assert app.state.review_runtime.provider is odoo_adapter
    finally:

        async def close() -> None:
            await odoo_adapter.aclose()
            await hubspot_adapter.aclose()
            await app.state.database_engine.dispose()

        asyncio.run(close())


@pytest.mark.parametrize(
    "hubspot_values",
    [
        {"hubspot_service_key": "test-hubspot-key"},
        {
            "hubspot_service_key": "test-hubspot-key",
            "hubspot_pipeline_id": "default",
        },
    ],
)
def test_partial_hubspot_configuration_keeps_sync_executor_unset(
    hubspot_values: dict[str, str],
) -> None:
    settings = Settings(
        _env_file=None,
        odoo_base_url="http://odoo.test",
        odoo_database="opsflow_test",
        odoo_api_key="test-api-key",
        odoo_company_id=1,
        odoo_warehouse_id=2,
        odoo_pricelist_id=3,
        **hubspot_values,
    )
    app = create_app(settings)
    odoo_adapter = app.state.odoo_adapter
    try:
        assert isinstance(odoo_adapter, OdooERPAdapter)
        assert app.state.hubspot_adapter is None
        assert app.state.order_sync_step_executor is None
    finally:

        async def close() -> None:
            await odoo_adapter.aclose()
            await app.state.database_engine.dispose()

        asyncio.run(close())
