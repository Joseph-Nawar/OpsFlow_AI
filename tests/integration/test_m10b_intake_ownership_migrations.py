"""Isolated PostgreSQL migration proofs for M10B intake ownership."""

import asyncio
import os
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_9_REVISION = "0006_phase9_order_syncs"
M10B_REVISION = "0007_phase7_intake_ownership"


def test_m10b_migration_revision_is_child_of_phase9_head() -> None:
    migration = runpy.run_path(
        str(REPOSITORY_ROOT / "alembic/versions/0007_phase7_intake_ownership.py")
    )
    assert migration["revision"] == M10B_REVISION
    assert migration["down_revision"] == PHASE_9_REVISION


def test_upgrade_downgrade_and_reupgrade_preserve_existing_orders(
    migration_test_database_url: str,
) -> None:
    asyncio.run(_assert_migration_lifecycle(migration_test_database_url))


async def _assert_migration_lifecycle(database_url: str) -> None:
    _run_alembic(database_url, "downgrade", "base")
    _run_alembic(database_url, "upgrade", PHASE_9_REVISION)
    order_id = uuid4()
    engine = create_async_engine(database_url)
    created_at = datetime(2030, 1, 1, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO orders "
                    "(id, state, created_at) VALUES (:id, 'PROCESSING', :created_at)"
                ),
                {"id": order_id, "created_at": created_at},
            )
    finally:
        await engine.dispose()

    _run_alembic(database_url, "upgrade", M10B_REVISION)
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("orders")}
            )
            assert {"intake_claim_token", "intake_claim_expires_at"} <= columns
            row = (
                await connection.execute(
                    text(
                        "SELECT intake_claim_token, intake_claim_expires_at "
                        "FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            ).one()
            assert row == (None, None)
            with pytest.raises(DBAPIError):
                await connection.execute(
                    text("UPDATE orders SET intake_claim_token = :token WHERE id = :id"),
                    {"token": uuid4(), "id": order_id},
                )
    finally:
        await engine.dispose()

    _run_alembic(database_url, "downgrade", PHASE_9_REVISION)
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("orders")}
            )
            assert "intake_claim_token" not in columns
            assert "intake_claim_expires_at" not in columns
            assert (
                await connection.scalar(
                    text("SELECT id FROM orders WHERE id = :id"), {"id": order_id}
                )
            ) == order_id
    finally:
        await engine.dispose()

    _run_alembic(database_url, "upgrade", "head")


def _run_alembic(database_url: str, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["OPSFLOW_DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return f"{result.stdout}\n{result.stderr}"
