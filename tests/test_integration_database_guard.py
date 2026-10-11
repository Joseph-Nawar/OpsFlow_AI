from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _collect_integration_tests(environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/integration",
            "--collect-only",
            "-q",
            "--no-cov",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_direct_integration_invocation_requires_explicit_disposable_target() -> None:
    environment = os.environ.copy()
    environment.pop("OPSFLOW_INTEGRATION_TEST_DATABASE_URL", None)

    result = _collect_integration_tests(environment)

    assert result.returncode != 0
    assert "OPSFLOW_INTEGRATION_TEST_DATABASE_URL" in result.stdout + result.stderr


def test_direct_integration_invocation_loads_guard_before_checking_target_identity() -> None:
    environment = os.environ.copy()
    environment["OPSFLOW_INTEGRATION_TEST_DATABASE_URL"] = (
        "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:59998/opsflow_integration_probe"
    )

    result = _collect_integration_tests(environment)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "dedicated integration-test database identity could not be verified" in output
    assert "ModuleNotFoundError" not in output


@pytest.mark.parametrize(
    "target_url",
    [
        "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:55432/opsflow_prod",
        "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:55432/opsflow",
        "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_migration_test",
        "postgresql+asyncpg://opsflow:opsflow@db.example.invalid:5432/opsflow_integration_ci",
        "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_integration_ci?options=-csearch_path=public",
        "sqlite+aiosqlite:///integration.db",
    ],
)
def test_direct_integration_invocation_rejects_unapproved_targets(target_url: str) -> None:
    environment = os.environ.copy()
    environment["OPSFLOW_INTEGRATION_TEST_DATABASE_URL"] = target_url

    result = _collect_integration_tests(environment)

    assert result.returncode != 0
    assert "dedicated integration-test database" in result.stdout + result.stderr


def test_ci_preflights_and_migrates_the_explicit_integration_database() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text()
    preflight = "      - name: Verify integration database before migrations"
    migration = "      - name: Apply migrations"
    current = "      - name: Check migration state"
    tests = "      - name: Run backend tests"

    assert preflight in workflow
    assert migration in workflow
    assert current in workflow
    assert tests in workflow
    preflight_start = workflow.index(preflight)
    migration_start = workflow.index(migration)
    current_start = workflow.index(current)
    tests_start = workflow.index(tests)
    assert preflight_start < migration_start < current_start < tests_start

    preflight_step = workflow[preflight_start:migration_start]
    migration_step = workflow[migration_start:current_start]
    current_step = workflow[current_start:tests_start]
    assert "uv run pytest tests/integration --collect-only -q --no-cov" in preflight_step
    assert (
        "OPSFLOW_DATABASE_URL: ${{ env.OPSFLOW_INTEGRATION_TEST_DATABASE_URL }}" in migration_step
    )
    assert "uv run alembic upgrade head" in migration_step
    assert "OPSFLOW_DATABASE_URL: ${{ env.OPSFLOW_INTEGRATION_TEST_DATABASE_URL }}" in current_step
    assert "uv run alembic current" in current_step
    assert "OPSFLOW_INTEGRATION_TEST_DATABASE_URL:" in workflow
    assert "run: uv run pytest" in workflow[tests_start:]
