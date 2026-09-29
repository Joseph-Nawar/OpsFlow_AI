"""Safety checks for the isolated destructive-migration database fixture."""

import pytest


def test_missing_migration_database_configuration_skips_safely(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.delenv("OPSFLOW_MIGRATION_TEST_DATABASE_URL", raising=False)

    with pytest.raises(pytest.skip.Exception, match="isolated migration database"):
        request.getfixturevalue("migration_test_database_url")


def test_migration_database_cannot_alias_the_configured_development_database(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.setenv(
        "OPSFLOW_DATABASE_URL",
        "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow",
    )
    monkeypatch.setenv(
        "OPSFLOW_MIGRATION_TEST_DATABASE_URL",
        "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:5432/opsflow",
    )

    with pytest.raises(pytest.fail.Exception, match="development database"):
        request.getfixturevalue("migration_test_database_url")


def test_migration_database_rejects_same_database_name_with_another_role(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.setenv(
        "OPSFLOW_DATABASE_URL",
        "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow",
    )
    monkeypatch.setenv(
        "OPSFLOW_MIGRATION_TEST_DATABASE_URL",
        "postgresql+asyncpg://migration:other@localhost:5432/opsflow",
    )

    with pytest.raises(pytest.fail.Exception, match="development database"):
        request.getfixturevalue("migration_test_database_url")
