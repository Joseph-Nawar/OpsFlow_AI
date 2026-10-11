"""Safety checks for the isolated destructive-migration database fixture."""

import pytest

from tests import integration_database_guard

NORMAL_URL = "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow"
MIGRATION_URL = "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_migration_test"


def _install_identity_engine(
    monkeypatch: pytest.MonkeyPatch, identity: tuple[str, str, int]
) -> list[str]:
    statements: list[str] = []

    class Result:
        def one(self) -> tuple[str, str, int]:
            return identity

    class Connection:
        async def execute(self, statement: object) -> Result:
            statements.append(str(statement))
            return Result()

    class ConnectionContext:
        async def __aenter__(self) -> Connection:
            return connection

        async def __aexit__(self, *args: object) -> None:
            return None

    class Engine:
        def connect(self) -> ConnectionContext:
            return ConnectionContext()

        async def dispose(self) -> None:
            statements.append("disposed")

    connection = Connection()
    monkeypatch.setattr(
        integration_database_guard,
        "create_async_engine",
        lambda *args, **kwargs: Engine(),
        raising=False,
    )
    return statements


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


def test_migration_database_rejects_unapproved_production_like_name(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.setenv(
        "OPSFLOW_DATABASE_URL",
        "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow",
    )
    monkeypatch.setenv(
        "OPSFLOW_MIGRATION_TEST_DATABASE_URL",
        "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_prod",
    )

    with pytest.raises(
        pytest.fail.Exception,
        match="approved opsflow_migration_test identity",
    ):
        request.getfixturevalue("migration_test_database_url")


@pytest.mark.parametrize(
    "migration_url",
    [
        "postgresql+asyncpg://opsflow:opsflow@localhost:55432/opsflow_migration_test",
        "postgresql+asyncpg://opsflow:opsflow@unrelated-remote-host.example:5432/opsflow_migration_test",
    ],
)
def test_migration_database_rejects_same_name_on_unapproved_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    migration_url: str,
) -> None:
    monkeypatch.setenv("OPSFLOW_DATABASE_URL", NORMAL_URL)
    monkeypatch.setenv("OPSFLOW_MIGRATION_TEST_DATABASE_URL", migration_url)
    monkeypatch.setattr(
        integration_database_guard,
        "create_async_engine",
        lambda *args, **kwargs: pytest.fail("unapproved migration endpoint must not connect"),
        raising=False,
    )

    with pytest.raises(pytest.fail.Exception):
        request.getfixturevalue("migration_test_database_url")


@pytest.mark.parametrize(
    "identity",
    [
        ("another_database", "public", 5432),
        ("opsflow_migration_test", "private_schema", 5432),
        ("opsflow_migration_test", "public", 55432),
    ],
)
def test_migration_identity_verifier_rejects_wrong_connected_target(
    monkeypatch: pytest.MonkeyPatch,
    identity: tuple[str, str, int],
) -> None:
    statements = _install_identity_engine(monkeypatch, identity)
    verifier = getattr(integration_database_guard, "verify_migration_test_database_identity", None)

    assert callable(verifier), "migration test database needs a connected identity verifier"
    with pytest.raises(integration_database_guard.IntegrationDatabaseSafetyError):
        verifier(MIGRATION_URL)

    assert any("inet_server_port()" in statement for statement in statements)
    assert "disposed" in statements


def test_migration_identity_verifier_accepts_the_approved_connected_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements = _install_identity_engine(
        monkeypatch,
        ("opsflow_migration_test", "public", 5432),
    )
    verifier = getattr(integration_database_guard, "verify_migration_test_database_identity", None)

    assert callable(verifier), "migration test database needs a connected identity verifier"
    verifier(MIGRATION_URL)

    assert any("inet_server_port()" in statement for statement in statements)
    assert "disposed" in statements


def test_migration_fixture_checks_connected_identity_before_returning_url(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.setenv("OPSFLOW_DATABASE_URL", NORMAL_URL)
    monkeypatch.setenv("OPSFLOW_MIGRATION_TEST_DATABASE_URL", MIGRATION_URL)
    statements = _install_identity_engine(
        monkeypatch,
        ("opsflow_migration_test", "public", 5432),
    )

    result = request.getfixturevalue("migration_test_database_url")

    assert result == MIGRATION_URL
    assert any("inet_server_port()" in statement for statement in statements)
