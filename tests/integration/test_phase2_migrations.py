"""Real-PostgreSQL migration-chain tests for Phase 2."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

REPOSITORY_ROOT = Path(__file__).parents[2]
BASELINE_REVISION = "0001_baseline"
PHASE_2_REVISION = "0002_phase2_persistence"
CURRENT_HEAD_REVISION = "0006_phase9_order_syncs"


def test_migration_upgrade_downgrade_and_reupgrade(
    migration_test_database_url: str,
) -> None:
    _run_alembic(migration_test_database_url, "downgrade", "base")
    _run_alembic(migration_test_database_url, "upgrade", BASELINE_REVISION)
    _run_alembic(migration_test_database_url, "upgrade", PHASE_2_REVISION)
    assert PHASE_2_REVISION in _run_alembic(migration_test_database_url, "current")

    _run_alembic(migration_test_database_url, "downgrade", BASELINE_REVISION)
    table_names = asyncio.run(_table_names(migration_test_database_url))
    assert table_names == {"alembic_version"}

    _run_alembic(migration_test_database_url, "upgrade", "head")
    assert CURRENT_HEAD_REVISION in _run_alembic(migration_test_database_url, "current")


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


async def _table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
    finally:
        await engine.dispose()
