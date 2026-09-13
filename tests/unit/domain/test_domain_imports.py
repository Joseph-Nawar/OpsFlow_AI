import subprocess
import sys

FORBIDDEN_ROOTS = (
    "fastapi",
    "sqlalchemy",
    "asyncpg",
    "alembic",
    "opsflow.database",
    "opsflow.ai",
    "opsflow.integrations",
)


def test_domain_imports_are_infrastructure_independent() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import opsflow.domain; print('\\n'.join(sys.modules))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = set(result.stdout.splitlines())

    assert "opsflow.domain" in loaded
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in loaded
        for forbidden in FORBIDDEN_ROOTS
    )
