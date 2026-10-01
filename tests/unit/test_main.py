"""Application composition for optional Phase 9 Odoo provider settings."""

import asyncio

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


def test_missing_odoo_configuration_leaves_executor_unset() -> None:
    app = create_app(Settings(_env_file=None))
    try:
        assert app.state.order_sync_step_executor is None
        assert app.state.odoo_adapter is None
    finally:
        asyncio.run(app.state.database_engine.dispose())


def test_complete_odoo_configuration_composes_one_provider_and_executor() -> None:
    app = create_app(_odoo_settings())
    adapter = app.state.odoo_adapter
    try:
        assert isinstance(adapter, OdooERPAdapter)
        assert app.state.order_sync_step_executor is adapter
        assert isinstance(app.state.review_runtime, ReviewRuntime)
        assert app.state.review_runtime.provider is adapter
    finally:

        async def close() -> None:
            await adapter.aclose()
            await app.state.database_engine.dispose()

        asyncio.run(close())
