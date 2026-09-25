"""PostgreSQL proofs for the synthetic Phase 7 retryable demo seed."""

import asyncio
import importlib.util
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path
from typing import get_type_hints
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from opsflow.domain import OrderState
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderCreationIdempotencyModel,
    OrderModel,
    SourceDocumentModel,
)
from opsflow.settings import Settings

SCRIPT = Path("scripts/phase7_seed_retryable_demo.py")
FIXTURE = Path("fixtures/phase7/synthetic-order.txt")


def _seed_module():
    spec = importlib.util.spec_from_file_location("phase7_seed_retryable_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_seed_contract_is_frozen_and_slotted() -> None:
    DemoSeedResult = _seed_module().DemoSeedResult

    assert is_dataclass(DemoSeedResult)
    assert DemoSeedResult.__dataclass_params__.frozen is True
    assert hasattr(DemoSeedResult, "__slots__")
    hints = get_type_hints(DemoSeedResult)
    assert hints["order_id"] is UUID
    assert hints["state"] is OrderState

    result = DemoSeedResult(
        order_id=UUID("00000000-0000-0000-0000-000000000001"),
        state=OrderState.FAILED_RETRYABLE,
        failure_origin=OrderState.PROCESSING,
    )
    with pytest.raises(FrozenInstanceError):
        result.state = OrderState.PROCESSING  # type: ignore[misc]


@pytest.mark.parametrize(
    ("origin", "key", "message_id", "failure_origin"),
    (
        (
            "processing",
            "phase7-processing-001",
            "phase7-message-processing-001",
            OrderState.PROCESSING,
        ),
        (
            "extracted",
            "phase7-extracted-001",
            "phase7-message-extracted-001",
            OrderState.EXTRACTED,
        ),
    ),
)
def test_demo_seed_creates_the_expected_retryable_failure(
    origin: str,
    key: str,
    message_id: str,
    failure_origin: OrderState,
) -> None:
    seed_retryable_demo = _seed_module().seed_retryable_demo

    async def run() -> None:
        result = await seed_retryable_demo(origin, Settings())
        assert result.state is OrderState.FAILED_RETRYABLE
        assert result.failure_origin is failure_origin
        await _assert_persisted_seed(result.order_id, key, message_id, failure_origin)
        await _delete_order(result.order_id)

    asyncio.run(run())


def test_demo_seed_cli_accepts_only_the_two_origins() -> None:
    for origin in ("processing", "extracted"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--origin", origin],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert set(output) == {"origin", "order_id", "state", "failure_origin"}
        assert output["origin"] == origin
        assert output["state"] == OrderState.FAILED_RETRYABLE.value
        assert output["failure_origin"] in {
            OrderState.PROCESSING.value,
            OrderState.EXTRACTED.value,
        }
        asyncio.run(_delete_order(UUID(output["order_id"])))

    invalid = subprocess.run(
        [sys.executable, str(SCRIPT), "--origin", "syncing"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode != 0


async def _assert_persisted_seed(
    order_id: UUID,
    key: str,
    message_id: str,
    failure_origin: OrderState,
) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            order = await session.get(OrderModel, order_id)
            assert order is not None
            assert OrderState(order.state) is OrderState.FAILED_RETRYABLE
            assert OrderState(order.failure_origin) is failure_origin

            source = (
                await session.scalars(
                    select(SourceDocumentModel).where(SourceDocumentModel.order_id == order_id)
                )
            ).one()
            assert source.name == FIXTURE.name
            assert source.document_type == "EMAIL_BODY"
            assert source.mime_type == "text/plain"
            import hashlib

            assert source.sha256 == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
            assert source.message_id == message_id

            idempotency = (
                await session.scalars(
                    select(OrderCreationIdempotencyModel).where(
                        OrderCreationIdempotencyModel.idempotency_key == key
                    )
                )
            ).one()
            assert idempotency.order_id == order_id
            audits = (
                await session.scalars(
                    select(AuditEventModel)
                    .where(AuditEventModel.order_id == order_id)
                    .order_by(AuditEventModel.occurred_at, AuditEventModel.id)
                )
            ).all()
            expected_events = (
                [
                    "ORDER_RECEIVED",
                    "ORDER_PROCESSING_STARTED",
                    "ORDER_PROCESSING_FAILED",
                ]
                if failure_origin is OrderState.PROCESSING
                else [
                    "ORDER_RECEIVED",
                    "ORDER_PROCESSING_STARTED",
                    "ORDER_EXTRACTION_COMPLETED",
                    "ORDER_VALIDATION_FAILED",
                ]
            )
            assert [event.event_type for event in audits] == expected_events
            snapshots = (
                await session.scalars(
                    select(ExtractionSnapshotModel).where(
                        ExtractionSnapshotModel.order_id == order_id
                    )
                )
            ).all()
            assert snapshots == []
    finally:
        await engine.dispose()


async def _delete_order(order_id: UUID) -> None:
    from sqlalchemy import delete

    from opsflow.persistence.models import (
        AuditEventModel,
        ExtractionSnapshotModel,
        OrderCreationIdempotencyModel,
        OrderLineModel,
        OrderModel,
        ReviewRevisionModel,
        SourceDocumentModel,
        ValidationIssueModel,
    )

    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            for model in (
                ReviewRevisionModel,
                ValidationIssueModel,
                ExtractionSnapshotModel,
                AuditEventModel,
                OrderLineModel,
                SourceDocumentModel,
                OrderCreationIdempotencyModel,
            ):
                await session.execute(delete(model).where(model.order_id == order_id))
            await session.execute(delete(OrderModel).where(OrderModel.id == order_id))
    finally:
        await engine.dispose()
