"""Minimal async PostgreSQL engine and readiness support."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from opsflow.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the application async engine from runtime settings."""

    return create_async_engine(settings.database_url, pool_pre_ping=True)


async def database_is_available(engine: AsyncEngine) -> bool:
    """Return whether PostgreSQL accepts a lightweight SELECT 1 query."""

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
