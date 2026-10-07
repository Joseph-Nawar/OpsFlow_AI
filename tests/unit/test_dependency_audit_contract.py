"""Repository contract tests for the pinned production dependency audit."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_python_audit_is_frozen_production_only_and_strict() -> None:
    script = (ROOT / "scripts/audit-production-dependencies.sh").read_text()

    assert "uv export --frozen --no-dev --no-emit-project --format requirements.txt" in script
    assert "uvx --from 'pip-audit==2.10.1' pip-audit" in script
    assert "--requirement /dev/stdin --no-deps --disable-pip --strict" in script
    assert "|| true" not in script


def test_makefile_exposes_both_production_audits() -> None:
    makefile = (ROOT / "Makefile").read_text()

    assert "dependency-audit:" in makefile
    assert "frontend-audit:" in makefile
    assert "$(NPM) audit --omit=dev --audit-level=high --prefix web" in makefile
