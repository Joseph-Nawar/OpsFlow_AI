"""Safety contracts for the isolated Phase 12 local demo composition."""

import asyncio
import json
from pathlib import Path

import pytest
from scripts.phase12_demo import (
    DEMO_SOURCE_PATH,
    Phase12FixtureProvider,
    check_demo_environment,
    create_local_demo_app,
)

from opsflow.extraction.errors import ProviderError
from opsflow.extraction.provider import StructuredGenerationRequest


def _request(source: str) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        prompt_version="phase4-extraction-v1",
        system_instruction="extract only",
        user_content=(
            f"SOURCE_LOCATION: text:body\nSOURCE_CONTENT_BEGIN\n{source}\nSOURCE_CONTENT_END"
        ),
        response_schema={"type": "object"},
    )


def test_demo_fixture_is_a_checked_in_synthetic_purchase_order() -> None:
    source = DEMO_SOURCE_PATH.read_text(encoding="utf-8")

    assert "PO-DEMO-2041" in source
    assert "Acme Industries" in source
    assert "SKU-001" in source
    assert "$15.00" in source
    assert "synthetic" in source.lower()


def test_fixture_provider_returns_grounded_evidence_for_the_fixture() -> None:
    source = DEMO_SOURCE_PATH.read_text(encoding="utf-8")
    provider = Phase12FixtureProvider()

    result = asyncio.run(provider.generate_structured(_request(source)))

    assert result.payload["po_number"] == "PO-DEMO-2041"
    assert result.payload["lines"][0]["submitted_price"] == "15.00"
    assert result.payload["evidence"]
    assert all(item["quote"] in source for item in result.payload["evidence"])


def test_fixture_provider_rejects_any_document_other_than_the_checked_in_fixture() -> None:
    provider = Phase12FixtureProvider()

    with pytest.raises(ProviderError, match="checked-in synthetic fixture"):
        asyncio.run(provider.generate_structured(_request("Private business document")))


@pytest.mark.parametrize(
    "environment",
    [
        {"GEMINI_API_KEY": "present"},
        {"OPSFLOW_GEMINI_API_KEY": "present"},
        {"OPSFLOW_ODOO_API_KEY": "present"},
        {"OPSFLOW_HUBSPOT_SERVICE_KEY": "present"},
        {"OPSFLOW_DATABASE_URL": "postgresql://remote.invalid/database"},
    ],
)
def test_demo_refuses_real_provider_or_database_environment(environment: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="(?i)unset before starting"):
        check_demo_environment(environment)


def test_fixture_path_is_inside_the_repository() -> None:
    assert DEMO_SOURCE_PATH.is_relative_to(Path(__file__).resolve().parents[2])


def test_demo_app_composition_disables_all_live_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPSFLOW_DATABASE_URL",
        "OPSFLOW_ORCHESTRATION_TOKEN",
        "OPSFLOW_REVIEW_DEV_OPERATORS",
        "OPSFLOW_GEMINI_API_KEY",
        "OPSFLOW_ODOO_API_KEY",
        "OPSFLOW_HUBSPOT_SERVICE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "database_url": (
                    "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:5432/opsflow_phase12_demo"
                ),
                "orchestration_token": "synthetic-orchestration-token",
                "reviewer_token": "synthetic-reviewer-token",
                "approver_token": "synthetic-approver-token",
                "order_id": None,
            }
        ),
        encoding="utf-8",
    )
    state_path.chmod(0o600)

    app = create_local_demo_app(state_path)
    try:
        assert app.state.orchestration_runtime.extraction_provider_factory is Phase12FixtureProvider
        assert app.state.orchestration_token.get_secret_value() == "synthetic-orchestration-token"
        assert app.state.odoo_adapter is None
        assert app.state.hubspot_adapter is None
        assert app.state.order_sync_step_executor is None
    finally:
        asyncio.run(app.state.database_engine.dispose())
