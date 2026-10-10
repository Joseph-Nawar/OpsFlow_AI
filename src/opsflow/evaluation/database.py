"""Fail-closed database selection and cleanup for full evaluation runs."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import delete, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from opsflow.persistence.models import Base
from opsflow.settings import Settings

_EVALUATION_DATABASE_ENV = "OPSFLOW_EVALUATION_DATABASE_URL"
_DATABASE_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,62}\Z", re.ASCII)

# Explicit child-before-parent deletion order. alembic_version is intentionally absent.
_APPLICATION_DELETE_ORDER = (
    "order_syncs",
    "notification_deliveries",
    "review_revisions",
    "extraction_snapshots",
    "order_creation_idempotency",
    "validation_issues",
    "order_lines",
    "audit_events",
    "source_documents",
    "orders",
)


class EvaluationDatabaseSafetyError(RuntimeError):
    """Raised when evaluation database isolation cannot be proven."""


@dataclass(frozen=True, slots=True)
class EvaluationDatabaseConfig:
    """Database URLs and the database name approved for evaluation cleanup."""

    evaluation_url: str
    normal_url: str
    migration_test_url: str | None
    evaluation_database_name: str

    @property
    def url(self) -> URL:
        """Return the parsed evaluation URL without exposing it in diagnostics."""

        return make_url(self.evaluation_url)

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        normal_url: str,
        migration_test_url: str | None,
    ) -> EvaluationDatabaseConfig:
        evaluation_url = environ.get(_EVALUATION_DATABASE_ENV)
        if (
            evaluation_url is None
            or not evaluation_url.strip()
            or evaluation_url != evaluation_url.strip()
        ):
            raise EvaluationDatabaseSafetyError(
                "OPSFLOW_EVALUATION_DATABASE_URL must identify a dedicated PostgreSQL database"
            )

        try:
            target = _strict_postgresql_url(evaluation_url, label="evaluation")
            normal = _strict_postgresql_url(normal_url, label="normal")
            migration = (
                _strict_postgresql_url(migration_test_url, label="migration-test")
                if migration_test_url is not None
                else None
            )
        except (TypeError, ValueError, SQLAlchemyError) as error:
            raise EvaluationDatabaseSafetyError(
                "evaluation, normal, and configured migration-test database identities "
                "must be provable"
            ) from error

        target_name = _required_database_name(target, label="evaluation")
        normal_name = _required_database_name(normal, label="normal")
        migration_name = (
            _required_database_name(migration, label="migration-test")
            if migration is not None
            else None
        )
        if target_name in (normal_name, migration_name):
            raise EvaluationDatabaseSafetyError(
                "evaluation database name must differ from normal and migration-test database names"
            )

        config = cls(
            evaluation_url=evaluation_url,
            normal_url=normal_url,
            migration_test_url=migration_test_url,
            evaluation_database_name=target_name,
        )
        assert_evaluation_database_isolated(config)
        return config


def _strict_postgresql_url(value: str | URL | None, *, label: str) -> URL:
    if isinstance(value, str) and (not value.strip() or value != value.strip()):
        raise ValueError(f"{label} URL is blank")
    if value is None:
        raise ValueError(f"{label} URL is blank")
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg":
        raise ValueError(f"{label} URL must use postgresql+asyncpg")
    if url.query or url.host is None or not url.host.strip() or url.username is None:
        raise ValueError(f"{label} URL identity is ambiguous")
    if not url.username.strip():
        raise ValueError(f"{label} URL user is blank")
    _required_database_name(url, label=label)
    return url


def _required_database_name(url: URL, *, label: str) -> str:
    database_name = url.database
    if (
        database_name is None
        or not database_name.strip()
        or database_name != database_name.strip()
        or _DATABASE_NAME_PATTERN.fullmatch(database_name) is None
    ):
        raise ValueError(f"{label} database name is blank or ambiguous")
    return database_name


def _url_identity(url: URL) -> tuple[object, ...]:
    return (
        url.drivername,
        url.username,
        url.host.lower() if url.host is not None else None,
        url.port or 5432,
        url.database,
        tuple(sorted(url.query.items())),
    )


def assert_evaluation_database_isolated(config: EvaluationDatabaseConfig) -> None:
    """Revalidate strict URL shape and distinct database names before any cleanup."""

    try:
        evaluation = _strict_postgresql_url(config.evaluation_url, label="evaluation")
        normal = _strict_postgresql_url(config.normal_url, label="normal")
        migration = (
            _strict_postgresql_url(config.migration_test_url, label="migration-test")
            if config.migration_test_url is not None
            else None
        )
        evaluation_name = _required_database_name(evaluation, label="evaluation")
        normal_name = _required_database_name(normal, label="normal")
        migration_name = (
            _required_database_name(migration, label="migration-test")
            if migration is not None
            else None
        )
    except (TypeError, ValueError, SQLAlchemyError) as error:
        raise EvaluationDatabaseSafetyError(
            "evaluation database isolation cannot be proven from the configured URLs"
        ) from error

    if config.evaluation_database_name != evaluation_name:
        raise EvaluationDatabaseSafetyError(
            "configured evaluation database name does not match its URL"
        )
    if evaluation_name in (normal_name, migration_name):
        raise EvaluationDatabaseSafetyError(
            "evaluation database name aliases a normal or migration-test database"
        )


async def reset_evaluation_application_data(
    config: EvaluationDatabaseConfig,
    engine: AsyncEngine,
) -> None:
    """Delete only application rows after validating both configured and connected identity."""

    assert_evaluation_database_isolated(config)
    try:
        engine_url = _strict_postgresql_url(engine.url, label="engine")
        evaluation_url = _strict_postgresql_url(config.evaluation_url, label="evaluation")
    except (TypeError, ValueError, SQLAlchemyError) as error:
        raise EvaluationDatabaseSafetyError(
            "evaluation engine identity cannot be proven"
        ) from error
    if _url_identity(engine_url) != _url_identity(evaluation_url):
        raise EvaluationDatabaseSafetyError("evaluation engine does not match the guarded target")

    if set(_APPLICATION_DELETE_ORDER) != set(Base.metadata.tables):
        raise EvaluationDatabaseSafetyError(
            "application cleanup allowlist does not match application tables"
        )

    async with engine.begin() as connection:
        identity = (
            await connection.execute(text("SELECT current_database(), current_schema()"))
        ).one()
        if identity[0] != config.evaluation_database_name or identity[1] != "public":
            raise EvaluationDatabaseSafetyError(
                "connected PostgreSQL database identity is not the guarded target"
            )
        for table_name in _APPLICATION_DELETE_ORDER:
            await connection.execute(delete(Base.metadata.tables[table_name]))


def confirm_current_migration_head(alembic_config: Config, expected_revision: str) -> None:
    """Require the guarded evaluation DB and code checkout to share the expected Alembic head."""

    config = EvaluationDatabaseConfig.from_environment(
        os.environ,
        Settings().database_url,
        os.environ.get("OPSFLOW_MIGRATION_TEST_DATABASE_URL"),
    )
    script = ScriptDirectory.from_config(alembic_config)
    expected_heads = script.get_heads()
    if expected_heads != [expected_revision]:
        raise EvaluationDatabaseSafetyError(
            "expected revision does not match the repository migration head"
        )

    engine = create_async_engine(config.evaluation_url, poolclass=NullPool)

    async def read_heads() -> tuple[str, ...]:
        async with engine.connect() as connection:
            connected_name, connected_schema = (
                await connection.execute(text("SELECT current_database(), current_schema()"))
            ).one()
            if connected_name != config.evaluation_database_name or connected_schema != "public":
                raise EvaluationDatabaseSafetyError(
                    "migration check is not connected to the guarded evaluation database"
                )
            return await connection.run_sync(
                lambda sync_connection: tuple(
                    MigrationContext.configure(sync_connection).get_current_heads()
                )
            )

    try:
        current_heads = asyncio.run(read_heads())
    except Exception as error:
        if isinstance(error, EvaluationDatabaseSafetyError):
            raise
        raise EvaluationDatabaseSafetyError(
            "evaluation database migration state could not be verified"
        ) from error
    finally:
        asyncio.run(engine.dispose())

    if list(current_heads) != expected_heads:
        raise EvaluationDatabaseSafetyError("evaluation database migration head is not current")
