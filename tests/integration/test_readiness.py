import asyncio

import httpx

from opsflow.main import create_app
from opsflow.settings import Settings

UNAVAILABLE_DATABASE_URL = "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:65432/opsflow"


def test_ready_reports_database_readiness() -> None:
    response = _request("/ready", Settings())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok"},
    }


def test_ready_reports_database_unavailable() -> None:
    response = _request("/ready", Settings(database_url=UNAVAILABLE_DATABASE_URL))

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable"},
    }
    assert "exception" not in response.text.lower()
    assert "password" not in response.text.lower()


def test_health_stays_live_when_database_is_unavailable() -> None:
    response = _request("/health", Settings(database_url=UNAVAILABLE_DATABASE_URL))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _request(path: str, settings: Settings) -> httpx.Response:
    return asyncio.run(_request_async(path, settings))


async def _request_async(path: str, settings: Settings) -> httpx.Response:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)
