"""Seed one synthetic Phase 7 retryable failure through the real service."""

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from opsflow.application.errors import BusinessDataProviderError
from opsflow.application.orchestration import execute_orchestration_intake
from opsflow.database import create_engine, create_sessionmaker
from opsflow.domain import OrderState, SourceDocumentType
from opsflow.extraction.errors import ProviderUnavailableError
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.provider import StructuredGenerationResult
from opsflow.orchestration.composition import build_orchestration_runtime
from opsflow.orchestration.contracts import OrchestrationIntakeCommand
from opsflow.settings import Settings

type DemoRetryOrigin = Literal["processing", "extracted"]

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures/phase7/synthetic-order.txt"
ACTOR = "orchestration:n8n"

_PROVIDER_PAYLOAD = {
    "customer_name": "Acme Industries",
    "customer_reference": "CUST-001",
    "po_number": "PO-SYNTHETIC",
    "order_date": "2025-01-01",
    "requested_delivery_date": "2025-01-08",
    "currency": "USD",
    "lines": [
        {
            "sku": "SKU-001",
            "description": "Widget",
            "quantity": "1",
            "submitted_price": "10",
        }
    ],
    "notes": None,
    "evidence": [],
}


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    """Bounded result emitted by the synthetic demo seed."""

    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None


class _RetryableBusinessDataProvider:
    async def get_validation_data(self, request: object) -> object:
        del request
        raise BusinessDataProviderError()


def _command(origin: DemoRetryOrigin, content: bytes) -> OrchestrationIntakeCommand:
    if origin == "processing":
        key = "phase7-processing-001"
        message_id = "phase7-message-processing-001"
    elif origin == "extracted":
        key = "phase7-extracted-001"
        message_id = "phase7-message-extracted-001"
    else:
        raise ValueError("origin must be processing or extracted")
    return OrchestrationIntakeCommand(
        content=content,
        document_type=SourceDocumentType.EMAIL_BODY,
        filename="synthetic-order.txt",
        mime_type="text/plain",
        message_id=message_id,
        idempotency_key=key,
    )


def _runtime(origin: DemoRetryOrigin, settings: Settings):
    extraction_factory: Callable[[], FakeProvider]
    if origin == "processing":

        def processing_factory() -> FakeProvider:
            return FakeProvider((ProviderUnavailableError(),))

        extraction_factory = processing_factory
    elif origin == "extracted":

        def extracted_factory() -> FakeProvider:
            return FakeProvider((StructuredGenerationResult(payload=_PROVIDER_PAYLOAD.copy()),))

        extraction_factory = extracted_factory
    else:
        raise ValueError("origin must be processing or extracted")

    runtime = build_orchestration_runtime(
        settings,
        extraction_provider_factory=extraction_factory,
    )
    if origin == "extracted":
        runtime = replace(runtime, business_data_provider=_RetryableBusinessDataProvider())
    return runtime


async def seed_retryable_demo(
    origin: DemoRetryOrigin,
    settings: Settings,
) -> DemoSeedResult:
    """Create one retryable demo failure through the Phase 7 application service."""

    if origin not in ("processing", "extracted"):
        raise ValueError("origin must be processing or extracted")
    content = FIXTURE_PATH.read_bytes()
    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            result = await execute_orchestration_intake(
                session,
                _command(origin, content),
                _runtime(origin, settings),
                ACTOR,
                datetime.now(UTC),
            )
        expected_origin = OrderState.PROCESSING if origin == "processing" else OrderState.EXTRACTED
        if result.state is not OrderState.FAILED_RETRYABLE:
            raise RuntimeError("demo seed did not create FAILED_RETRYABLE")
        if result.failure_origin is not expected_origin:
            raise RuntimeError("demo seed created the wrong failure origin")
        return DemoSeedResult(
            order_id=result.order_id,
            state=result.state,
            failure_origin=result.failure_origin,
        )
    finally:
        await engine.dispose()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", choices=("processing", "extracted"), required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    result = asyncio.run(seed_retryable_demo(args.origin, Settings()))
    print(
        json.dumps(
            {
                "origin": args.origin,
                "order_id": str(result.order_id),
                "state": result.state.value,
                "failure_origin": result.failure_origin.value
                if result.failure_origin is not None
                else None,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
