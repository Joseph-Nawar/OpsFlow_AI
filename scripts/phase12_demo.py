"""Isolated, provider-free Phase 12 evidence rehearsal using the real application."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import gettempdir
from typing import Any
from urllib.parse import urlsplit

import httpx
import uvicorn
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from opsflow.documents.models import DocumentInput
from opsflow.documents.processor import process_document
from opsflow.domain import SourceDocumentType
from opsflow.extraction.errors import ProviderError
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.prompt import build_extraction_request, render_canonical_document
from opsflow.extraction.provider import StructuredGenerationRequest, StructuredGenerationResult
from opsflow.main import create_app
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SOURCE_PATH = _REPO_ROOT / "fixtures/phase12/local-review-order.txt"
DEFAULT_STATE_PATH = Path(gettempdir()) / f"opsflow-phase12-demo-{os.getuid()}" / "state.json"
_DEMO_IDEMPOTENCY_KEY = "phase12-local-demo:PO-DEMO-2041:v1"
_DEMO_MESSAGE_ID = "synthetic-demo-message-2041"
_REQUIRED_DATABASE_NAME = "opsflow_phase12_demo"
_BLOCKED_ENVIRONMENT_NAMES = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPSFLOW_DATABASE_URL",
    "OPSFLOW_ORCHESTRATION_TOKEN",
    "OPSFLOW_REVIEW_DEV_OPERATORS",
)
_BLOCKED_ENVIRONMENT_PREFIXES = (
    "OPSFLOW_GEMINI_",
    "OPSFLOW_ODOO_",
    "OPSFLOW_HUBSPOT_",
)

_DEMO_PAYLOAD: dict[str, Any] = {
    "customer_name": "Acme Industries",
    "customer_reference": "CUST-001",
    "po_number": "PO-DEMO-2041",
    "order_date": "2026-11-19",
    "requested_delivery_date": "2026-11-30",
    "currency": "USD",
    "lines": [
        {
            "sku": "SKU-001",
            "description": "Widget",
            "quantity": "3",
            "submitted_price": "15.00",
        }
    ],
    "notes": None,
    "evidence": [
        {
            "field_path": "customer_name",
            "source_location": "text:body",
            "quote": "Customer: Acme Industries",
        },
        {
            "field_path": "customer_reference",
            "source_location": "text:body",
            "quote": "Customer reference: CUST-001",
        },
        {
            "field_path": "po_number",
            "source_location": "text:body",
            "quote": "PO number: PO-DEMO-2041",
        },
        {
            "field_path": "order_date",
            "source_location": "text:body",
            "quote": "Order date: 2026-11-19",
        },
        {
            "field_path": "requested_delivery_date",
            "source_location": "text:body",
            "quote": "Requested delivery date: 2026-11-30",
        },
        {
            "field_path": "currency",
            "source_location": "text:body",
            "quote": "Currency: USD",
        },
        {
            "field_path": "lines[0].sku",
            "source_location": "text:body",
            "quote": "Line 1 SKU: SKU-001",
        },
        {
            "field_path": "lines[0].description",
            "source_location": "text:body",
            "quote": "Line 1 description: Widget",
        },
        {
            "field_path": "lines[0].quantity",
            "source_location": "text:body",
            "quote": "Line 1 quantity: 3",
        },
        {
            "field_path": "lines[0].submitted_price",
            "source_location": "text:body",
            "quote": "Line 1 submitted unit price: $15.00",
        },
    ],
}


def check_demo_environment(environment: Mapping[str, str]) -> None:
    """Fail closed when real provider or non-demo application configuration exists."""

    blocked = [
        name
        for name, value in environment.items()
        if value.strip()
        and (
            name in _BLOCKED_ENVIRONMENT_NAMES
            or any(name.startswith(prefix) for prefix in _BLOCKED_ENVIRONMENT_PREFIXES)
        )
    ]
    if blocked:
        names = ", ".join(sorted(blocked))
        raise RuntimeError(
            f"Unset before starting the isolated demo: {names}. "
            "The demo never uses live providers or environment-loaded credentials."
        )


def _fixture_request() -> StructuredGenerationRequest:
    document = DocumentInput(
        document_type=SourceDocumentType.EMAIL_BODY,
        name=DEMO_SOURCE_PATH.name,
        mime_type="text/plain",
        content=DEMO_SOURCE_PATH.read_bytes(),
    )
    canonical = process_document(document)
    return build_extraction_request(render_canonical_document(canonical))


class Phase12FixtureProvider:
    """Use FakeProvider only for the byte-for-byte checked-in synthetic fixture."""

    def __init__(self) -> None:
        self._expected_request = _fixture_request().user_content
        self._provider = FakeProvider((StructuredGenerationResult(payload=_DEMO_PAYLOAD.copy()),))

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        if request.user_content != self._expected_request:
            raise ProviderError("local demo accepts only the checked-in synthetic fixture")
        return await self._provider.generate_structured(request)


def _state_path(value: str | None = None) -> Path:
    configured = value or os.environ.get("OPSFLOW_PHASE12_DEMO_STATE")
    return Path(configured).expanduser() if configured else DEFAULT_STATE_PATH


def _write_state(path: Path, state: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(path)
    path.chmod(0o600)


def _read_state(path: Path) -> dict[str, object]:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise RuntimeError("Initialize the isolated demo state before continuing.") from error
    if mode & 0o077:
        raise RuntimeError("Demo state permissions must be 0600; remove and reinitialize it.")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Demo state is unreadable; remove and reinitialize it.") from error
    if not isinstance(state, dict):
        raise RuntimeError("Demo state has an invalid format.")
    required = {
        "database_url",
        "orchestration_token",
        "reviewer_token",
        "approver_token",
        "order_id",
    }
    if not required.issubset(state):
        raise RuntimeError("Demo state is incomplete; remove and reinitialize it.")
    return state


def _validate_demo_database(database_url: str) -> None:
    try:
        parsed = make_url(database_url)
    except (TypeError, ValueError) as error:
        raise RuntimeError("Demo database URL is invalid.") from error
    if (
        parsed.drivername != "postgresql+asyncpg"
        or parsed.host not in {"localhost", "127.0.0.1", "::1"}
        or parsed.port != 5432
        or parsed.database != _REQUIRED_DATABASE_NAME
    ):
        raise RuntimeError(
            f"Demo database must be local PostgreSQL {_REQUIRED_DATABASE_NAME} on port 5432."
        )


def _initialize(path: Path, database_url: str) -> None:
    if path.exists():
        raise RuntimeError("Demo state already exists; preserve it or remove it explicitly first.")
    _validate_demo_database(database_url)
    state: dict[str, object] = {
        "database_url": database_url,
        "orchestration_token": secrets.token_urlsafe(32),
        "reviewer_token": secrets.token_urlsafe(32),
        "approver_token": secrets.token_urlsafe(32),
        "order_id": None,
    }
    _write_state(path, state)
    print(f"Isolated local demo state initialized at {path}")


def create_local_demo_app(path: Path | None = None):
    """Compose the real FastAPI app with synthetic-only settings and FakeProvider."""

    check_demo_environment(os.environ)
    state = _read_state(path or _state_path())
    database_url = str(state["database_url"])
    _validate_demo_database(database_url)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        orchestration_token=SecretStr(str(state["orchestration_token"])),
        gemini_api_key=None,
        gemini_model=None,
        gemini_timeout_seconds=None,
        review_base_url="http://127.0.0.1:5173",
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=SecretStr(str(state["reviewer_token"])),
                actor="phase12-local-reviewer",
                role=OperatorRole.REVIEWER,
            ),
            DevelopmentOperatorConfig(
                token=SecretStr(str(state["approver_token"])),
                actor="phase12-local-approver",
                role=OperatorRole.APPROVER,
            ),
        ),
        odoo_base_url=None,
        odoo_database=None,
        odoo_api_key=None,
        odoo_company_id=None,
        odoo_warehouse_id=None,
        odoo_pricelist_id=None,
        hubspot_service_key=None,
        hubspot_pipeline_id=None,
        hubspot_initial_stage_id=None,
        hubspot_portal_currency=None,
        hubspot_expected_portal_id=None,
    )
    return create_app(settings, extraction_provider_factory=Phase12FixtureProvider)


def _seed(path: Path, base_url: str) -> None:
    state = _read_state(path)
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Seed requests may target only the local HTTP application.")
    if state["order_id"] is not None:
        raise RuntimeError(
            "The synthetic fixture was already submitted; reset its isolated DB first."
        )
    response = httpx.post(
        f"{base_url.rstrip('/')}/v1/orchestration/intakes",
        headers={
            "Authorization": f"Bearer {state['orchestration_token']}",
            "Idempotency-Key": _DEMO_IDEMPOTENCY_KEY,
        },
        data={"document_type": "EMAIL_BODY", "message_id": _DEMO_MESSAGE_ID},
        files={
            "document": (
                DEMO_SOURCE_PATH.name,
                DEMO_SOURCE_PATH.read_bytes(),
                "text/plain",
            )
        },
        timeout=20,
    )
    if response.status_code != 201:
        raise RuntimeError(f"Synthetic intake failed with HTTP {response.status_code}.")
    result = response.json()
    if result.get("state") != "NEEDS_REVIEW":
        raise RuntimeError("Synthetic intake did not enter the expected review state.")
    state["order_id"] = result["order_id"]
    _write_state(path, state)
    print(f"Synthetic purchase order entered review: {result['order_id']} (NEEDS_REVIEW)")


def _serve(path: Path, port: int) -> None:
    app = create_local_demo_app(path)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", help="Private local demo state file")
    subcommands = parser.add_subparsers(dest="command", required=True)
    initialize = subcommands.add_parser("init", help="Create private ephemeral credentials")
    initialize.add_argument(
        "--database-url",
        default="postgresql+asyncpg://opsflow:opsflow@127.0.0.1:5432/opsflow_phase12_demo",
    )
    serve = subcommands.add_parser("serve", help="Run the real API on loopback only")
    serve.add_argument("--port", type=int, default=8000)
    seed = subcommands.add_parser("seed", help="Submit the tracked synthetic fixture via HTTP")
    seed.add_argument("--base-url", default="http://127.0.0.1:8000")
    arguments = parser.parse_args(argv)
    state_path = _state_path(arguments.state)

    try:
        if arguments.command == "init":
            _initialize(state_path, arguments.database_url)
        elif arguments.command == "serve":
            _serve(state_path, arguments.port)
        elif arguments.command == "seed":
            _seed(state_path, arguments.base_url)
    except (OSError, RuntimeError, httpx.HTTPError) as error:
        print(f"Demo stopped safely: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
