"""Require integration tests to use an explicitly named local disposable database."""

from __future__ import annotations

import asyncio
import re
from collections.abc import MutableMapping

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

INTEGRATION_DATABASE_ENV = "OPSFLOW_INTEGRATION_TEST_DATABASE_URL"
INTEGRATION_DATABASE_PREFIX = "opsflow_integration_"
MIGRATION_DATABASE_NAME = "opsflow_migration_test"
APPROVED_POSTGRESQL_PORT = 5432
_DATABASE_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}\Z", re.ASCII)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class IntegrationDatabaseSafetyError(RuntimeError):
    """Raised when the integration-test database cannot be proven disposable."""


def _parse_local_postgresql_url(value: str | None, *, label: str) -> URL:
    if value is None or not value.strip() or value != value.strip():
        raise IntegrationDatabaseSafetyError(
            f"{label} must identify a dedicated integration-test PostgreSQL database"
        )
    try:
        url = make_url(value)
    except (TypeError, ValueError) as error:
        raise IntegrationDatabaseSafetyError(f"{label} database identity is invalid") from error
    if (
        url.drivername != "postgresql+asyncpg"
        or url.query
        or url.host is None
        or url.host.lower() not in _LOOPBACK_HOSTS
        or not url.username
        or url.database is None
        or _DATABASE_NAME.fullmatch(url.database) is None
    ):
        raise IntegrationDatabaseSafetyError(
            f"{label} must identify a dedicated integration-test database on local PostgreSQL"
        )
    return url


def _require_approved_test_endpoint(url: URL, *, label: str) -> None:
    if url.port != APPROVED_POSTGRESQL_PORT:
        raise IntegrationDatabaseSafetyError(
            f"{label} must identify a dedicated integration-test database on the "
            "approved local PostgreSQL endpoint at port 5432"
        )


def configure_integration_database(environ: MutableMapping[str, str], normal_url: str) -> str:
    """Validate the disposable target and override app settings before tests import."""

    target_value = environ.get(INTEGRATION_DATABASE_ENV)
    target = _parse_local_postgresql_url(target_value, label=INTEGRATION_DATABASE_ENV)
    normal = _parse_local_postgresql_url(normal_url, label="OPSFLOW_DATABASE_URL")
    migration_value = environ.get("OPSFLOW_MIGRATION_TEST_DATABASE_URL")
    migration = (
        _parse_local_postgresql_url(migration_value, label="OPSFLOW_MIGRATION_TEST_DATABASE_URL")
        if migration_value is not None
        else None
    )
    _require_approved_test_endpoint(target, label=INTEGRATION_DATABASE_ENV)
    if migration is not None:
        _require_approved_test_endpoint(migration, label="OPSFLOW_MIGRATION_TEST_DATABASE_URL")

    if not target.database.startswith(INTEGRATION_DATABASE_PREFIX):
        raise IntegrationDatabaseSafetyError(
            "target must be a dedicated integration-test database named opsflow_integration_*"
        )
    if target.database in {normal.database, migration.database if migration is not None else None}:
        raise IntegrationDatabaseSafetyError(
            "integration-test database must differ from normal and migration-test databases"
        )
    if migration is not None and migration.database != MIGRATION_DATABASE_NAME:
        raise IntegrationDatabaseSafetyError(
            "migration database must use the approved opsflow_migration_test identity"
        )

    environ["OPSFLOW_DATABASE_URL"] = target_value
    return target_value


def verify_integration_database_identity(database_url: str) -> None:
    """Read connected identity before pytest can run migrations or test writes."""

    target = _parse_local_postgresql_url(database_url, label=INTEGRATION_DATABASE_ENV)
    _require_approved_test_endpoint(target, label=INTEGRATION_DATABASE_ENV)
    if target.database is None or not target.database.startswith(INTEGRATION_DATABASE_PREFIX):
        raise IntegrationDatabaseSafetyError(
            "target must be a dedicated integration-test database named opsflow_integration_*"
        )
    _verify_connected_database_identity(
        database_url,
        expected_name=target.database,
        label="dedicated integration-test",
    )


def verify_migration_test_database_identity(database_url: str) -> None:
    """Verify the destructive migration-test target before Alembic can use it."""

    target = _parse_local_postgresql_url(database_url, label="OPSFLOW_MIGRATION_TEST_DATABASE_URL")
    _require_approved_test_endpoint(target, label="OPSFLOW_MIGRATION_TEST_DATABASE_URL")
    if target.database != MIGRATION_DATABASE_NAME:
        raise IntegrationDatabaseSafetyError(
            "migration target must be the approved opsflow_migration_test database"
        )
    _verify_connected_database_identity(
        database_url,
        expected_name=MIGRATION_DATABASE_NAME,
        label="migration-test",
    )


def _verify_connected_database_identity(
    database_url: str,
    *,
    expected_name: str,
    label: str,
) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)

    async def read_identity() -> tuple[str | None, str | None, int | None]:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text("SELECT current_database(), current_schema(), inet_server_port()")
                )
            ).one()
            return row[0], row[1], row[2]

    try:
        identity = asyncio.run(read_identity())
    except Exception as error:
        raise IntegrationDatabaseSafetyError(
            f"{label} database identity could not be verified"
        ) from error
    finally:
        asyncio.run(engine.dispose())
    if identity != (expected_name, "public", APPROVED_POSTGRESQL_PORT):
        raise IntegrationDatabaseSafetyError(
            f"connected database is not the approved {label} target"
        )
