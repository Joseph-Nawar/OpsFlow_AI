"""HTTPX cleanup and cancellation behavior at the Odoo adapter boundary."""

import asyncio

import httpx
import pytest

from opsflow.odoo import OdooERPAdapter
from opsflow.settings import Settings


class _CancelOnceTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False
        self.closed = False
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return httpx.Response(200, json={"bounded": True}, request=request)

    async def aclose(self) -> None:
        self.closed = True


def test_canceled_json2_call_propagates_and_releases_http_resources() -> None:
    async def exercise() -> None:
        transport = _CancelOnceTransport()
        adapter = OdooERPAdapter(
            Settings(
                _env_file=None,
                odoo_base_url="http://odoo.test",
                odoo_database="opsflow_test",
                odoo_api_key="cancel-test-key-sentinel",
                odoo_company_id=1,
                odoo_warehouse_id=2,
                odoo_pricelist_id=3,
            ),
            transport=transport,
        )
        try:
            call = asyncio.create_task(adapter._json2_call("res.company", "read", ids=[1]))
            await transport.started.wait()
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            assert transport.cancelled
            assert await adapter._json2_call("res.company", "read", ids=[1]) == {"bounded": True}
        finally:
            await adapter.aclose()
        assert transport.closed

    asyncio.run(exercise())
