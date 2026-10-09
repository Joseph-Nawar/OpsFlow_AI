"""Test-only cleanup for the dedicated M11C PostgreSQL database."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine


async def clear_m11c_application_data(engine: AsyncEngine) -> None:
    """Clear only application rows in an explicitly named M11C test database."""

    url = make_url(str(engine.url))
    if url.get_backend_name() != "postgresql":
        raise AssertionError("M11C cleanup requires PostgreSQL")
    if url.database is None or not url.database.startswith("opsflow_m11c_"):
        raise AssertionError("M11C cleanup requires an opsflow_m11c_ database")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE "
                "notification_deliveries, order_syncs, validation_issues, "
                "extraction_snapshots, review_revisions, audit_events, "
                "order_lines, source_documents, order_creation_idempotency, orders "
                "RESTART IDENTITY CASCADE"
            )
        )


__all__ = ["clear_m11c_application_data"]
