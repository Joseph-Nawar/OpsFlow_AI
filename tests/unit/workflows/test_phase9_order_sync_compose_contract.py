"""Static security and readiness contract for Phase 9 local Compose wiring."""

import re
from pathlib import Path

COMPOSE_PATH = Path("docker-compose.yml")
ODOO_SETTINGS = {
    "OPSFLOW_ODOO_BASE_URL",
    "OPSFLOW_ODOO_DATABASE",
    "OPSFLOW_ODOO_API_KEY",
    "OPSFLOW_ODOO_COMPANY_ID",
    "OPSFLOW_ODOO_WAREHOUSE_ID",
    "OPSFLOW_ODOO_PRICELIST_ID",
}
HUBSPOT_SETTINGS = {
    "OPSFLOW_HUBSPOT_SERVICE_KEY",
    "OPSFLOW_HUBSPOT_PIPELINE_ID",
    "OPSFLOW_HUBSPOT_INITIAL_STAGE_ID",
    "OPSFLOW_HUBSPOT_PORTAL_CURRENCY",
    "OPSFLOW_HUBSPOT_EXPECTED_PORTAL_ID",
}


def _service_block(compose: str, service_name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service_name)}:\n(.*?)(?=^  [\w-]+:\n|^volumes:\n|\Z)",
        compose,
    )
    assert match is not None, f"Compose service {service_name!r} is missing"
    return match.group(1)


def test_phase9_provider_settings_are_api_only_and_readiness_keeps_preclaim_503() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    api = _service_block(compose, "api")
    n8n = _service_block(compose, "n8n")

    for name in ODOO_SETTINGS | HUBSPOT_SETTINGS:
        assert re.search(rf"(?m)^      {re.escape(name)}:", api), name
        assert not re.search(rf"(?m)^      {re.escape(name)}:", n8n), name

    assert "OPSFLOW_ORCHESTRATION_TOKEN" not in n8n
    assert not re.search(r"(?m)^    env_file:", n8n)
    assert "http://127.0.0.1:8000/ready" in api
    assert re.search(
        r"(?ms)^    depends_on:\n      api:\n        condition: service_healthy(?:\n|$)",
        n8n,
    )


def test_compose_pins_n8n_and_keeps_host_ports_local() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    n8n = _service_block(compose, "n8n")

    assert "image: n8nio/n8n:2.40.5" in n8n
    assert "n8n-data:/home/node/.n8n" in n8n
    assert '"127.0.0.1:5432:5432"' in _service_block(compose, "postgres")
    assert '"127.0.0.1:8000:8000"' in _service_block(compose, "api")
    assert '"127.0.0.1:5678:5678"' in n8n
