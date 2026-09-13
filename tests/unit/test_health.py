import asyncio

import httpx

from opsflow.main import app


def test_health_returns_liveness_response() -> None:
    response = asyncio.run(_request_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def _request_health() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get("/health")
