"""Real PostgreSQL migration and constraint tests for Phase 8 delivery records."""

import asyncio
import os
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    NotificationDeliveryModel,
    OrderModel,
    ReviewRevisionModel,
    SourceDocumentModel,
)
from opsflow.settings import Settings

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_6_REVISION = "0004_phase6_review_revisions"
PHASE_8_REVISION = "0005_phase8_notification_deliveries"
_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def test_phase8_migration_revision_is_child_of_phase6_head() -> None:
    migration = runpy.run_path(
        str(REPOSITORY_ROOT / "alembic/versions/0005_phase8_notification_deliveries.py")
    )

    assert migration["revision"] == PHASE_8_REVISION
    assert migration["down_revision"] == PHASE_6_REVISION


def test_clean_upgrade_and_notification_schema_constraints() -> None:
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")
    assert PHASE_8_REVISION in _run_alembic("current")
    asyncio.run(_assert_schema_and_constraints())


def test_phase8_downgrade_and_reupgrade_preserve_phase6_rows() -> None:
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", PHASE_6_REVISION)
    revision_id = asyncio.run(_insert_phase6_revision())

    _run_alembic("upgrade", PHASE_8_REVISION)
    assert PHASE_8_REVISION in _run_alembic("current")
    _run_alembic("downgrade", PHASE_6_REVISION)
    assert PHASE_6_REVISION in _run_alembic("current")
    assert asyncio.run(_revision_exists(revision_id))

    _run_alembic("upgrade", "head")
    assert PHASE_8_REVISION in _run_alembic("current")
    assert asyncio.run(_revision_exists(revision_id))


def _run_alembic(*arguments: str) -> str:
    environment = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return f"{result.stdout}\n{result.stderr}"


def _delivery_row(
    parent_order_id: object,
    parent_event_id: object,
    **overrides: object,
) -> NotificationDeliveryModel:
    values: dict[str, object] = {
        "id": uuid4(),
        "order_id": parent_order_id,
        "trigger_audit_event_id": parent_event_id,
        "channel": "SLACK",
        "kind": "REVIEW_REQUIRED",
        "payload": {"text": "Review is required."},
        "status": "PENDING",
        "attempt_count": 0,
        "claim_token": None,
        "claim_expires_at": None,
        "next_attempt_at": _NOW,
        "provider_reference": None,
        "last_failure_code": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return NotificationDeliveryModel(**values)


async def _assert_schema_and_constraints() -> None:
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    order_id, event_id = uuid4(), uuid4()
    async with session_factory() as session:
        session.add(OrderModel(id=order_id, state="RECEIVED", created_at=_NOW))
        await session.flush()
        session.add(
            AuditEventModel(
                id=event_id,
                order_id=order_id,
                event_type="ORDER_NEEDS_REVIEW",
                actor="system",
                occurred_at=_NOW,
                description="Review required.",
            )
        )
        await session.commit()

    try:
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
            assert "notification_deliveries" in table_names
            columns = await connection.run_sync(
                lambda sync: {
                    column["name"]
                    for column in inspect(sync).get_columns("notification_deliveries")
                }
            )
            assert columns == {
                "id",
                "order_id",
                "trigger_audit_event_id",
                "channel",
                "kind",
                "payload",
                "status",
                "attempt_count",
                "claim_token",
                "claim_expires_at",
                "next_attempt_at",
                "provider_reference",
                "last_failure_code",
                "created_at",
                "updated_at",
            }
            checks = await connection.run_sync(
                lambda sync: {
                    check["name"]
                    for check in inspect(sync).get_check_constraints("notification_deliveries")
                }
            )
            assert checks == {
                "ck_notification_deliveries_channel",
                "ck_notification_deliveries_kind",
                "ck_notification_deliveries_status",
                "ck_notification_deliveries_attempt_count",
                "ck_notification_deliveries_payload_object",
                "ck_notification_deliveries_claim_pair",
                "ck_notification_deliveries_provider_reference",
                "ck_notification_deliveries_failure_code",
            }
            primary_key = await connection.run_sync(
                lambda sync: inspect(sync).get_pk_constraint("notification_deliveries")
            )
            assert primary_key["constrained_columns"] == ["id"]
            assert primary_key["name"] == "pk_notification_deliveries"
            uniques = await connection.run_sync(
                lambda sync: {
                    constraint["name"]
                    for constraint in inspect(sync).get_unique_constraints(
                        "notification_deliveries"
                    )
                }
            )
            assert uniques == {"uq_notification_deliveries_trigger_channel_kind"}
            indexes = await connection.run_sync(
                lambda sync: {
                    index["name"]: index["column_names"]
                    for index in inspect(sync).get_indexes("notification_deliveries")
                }
            )
            assert indexes["ix_notification_deliveries_claim_eligibility"] == [
                "status",
                "next_attempt_at",
                "claim_expires_at",
            ]
            foreign_keys = await connection.run_sync(
                lambda sync: inspect(sync).get_foreign_keys("notification_deliveries")
            )
            assert {
                (
                    foreign_key["name"],
                    foreign_key["referred_table"],
                    foreign_key["options"].get("ondelete"),
                )
                for foreign_key in foreign_keys
            } == {
                ("fk_notification_deliveries_order", "orders", "CASCADE"),
                ("fk_notification_deliveries_trigger_event", "audit_events", "CASCADE"),
            }

        async with session_factory() as session:
            session.add(_delivery_row(order_id, event_id))
            await session.commit()

        for overrides in (
            {"channel": "EMAIL"},
            {"kind": "SYNC_FAILED"},
            {"status": "PROCESSING"},
            {"attempt_count": -1},
            {"attempt_count": 4},
            {"payload": ["not", "an", "object"]},
            {"status": "CLAIMED"},
            {"claim_token": uuid4()},
            {"provider_reference": "r" * 257},
            {"last_failure_code": "RAW_PROVIDER_ERROR"},
            {"last_failure_code": "x" * 65},
            {"order_id": uuid4()},
            {"trigger_audit_event_id": uuid4()},
        ):
            async with session_factory() as session:
                session.add(_delivery_row(order_id, event_id, **overrides))
                with pytest.raises(DBAPIError):
                    await session.flush()
                await session.rollback()

        async with session_factory() as session:
            session.add(
                _delivery_row(
                    order_id,
                    event_id,
                    channel="GMAIL",
                    kind="ORDER_APPROVED",
                    status="CLAIMED",
                    attempt_count=1,
                    claim_token=uuid4(),
                    claim_expires_at=_NOW,
                )
            )
            await session.commit()

        async with session_factory() as session:
            session.add(_delivery_row(order_id, event_id))
            with pytest.raises(DBAPIError):
                await session.flush()
            await session.rollback()

        cascade_order, cascade_event = uuid4(), uuid4()
        retained_order, retained_event = uuid4(), uuid4()
        async with session_factory() as session:
            session.add_all(
                [
                    OrderModel(id=cascade_order, state="RECEIVED", created_at=_NOW),
                    OrderModel(id=retained_order, state="RECEIVED", created_at=_NOW),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    AuditEventModel(
                        id=cascade_event,
                        order_id=cascade_order,
                        event_type="ORDER_NEEDS_REVIEW",
                        actor="system",
                        occurred_at=_NOW,
                        description="Review required.",
                    ),
                    AuditEventModel(
                        id=retained_event,
                        order_id=retained_order,
                        event_type="ORDER_NEEDS_REVIEW",
                        actor="system",
                        occurred_at=_NOW,
                        description="Review required.",
                    ),
                ]
            )
            await session.flush()
            order_delivery = _delivery_row(cascade_order, cascade_event)
            event_delivery = _delivery_row(retained_order, retained_event)
            session.add_all([order_delivery, event_delivery])
            await session.commit()
            await session.execute(delete(OrderModel).where(OrderModel.id == cascade_order))
            await session.commit()
            assert (
                await session.scalar(
                    select(NotificationDeliveryModel.id).where(
                        NotificationDeliveryModel.id == order_delivery.id
                    )
                )
                is None
            )
            await session.execute(
                delete(AuditEventModel).where(AuditEventModel.id == retained_event)
            )
            await session.commit()
            assert (
                await session.scalar(
                    select(NotificationDeliveryModel.id).where(
                        NotificationDeliveryModel.id == event_delivery.id
                    )
                )
                is None
            )
    finally:
        await engine.dispose()


async def _insert_phase6_revision() -> object:
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    order_id, source_id, snapshot_id, revision_id = uuid4(), uuid4(), uuid4(), uuid4()
    digest = "a" * 64
    async with session_factory() as session:
        session.add(OrderModel(id=order_id, state="RECEIVED", created_at=_NOW))
        await session.flush()
        session.add(
            SourceDocumentModel(
                id=source_id,
                order_id=order_id,
                position=0,
                document_type="PDF",
                name="order.pdf",
                mime_type="application/pdf",
                sha256=digest,
                message_id=None,
                storage_reference=None,
                metadata_=[],
            )
        )
        await session.flush()
        session.add(
            ExtractionSnapshotModel(
                id=snapshot_id,
                order_id=order_id,
                source_document_id=source_id,
                source_sha256=digest,
                source_document_type="PDF",
                payload={},
                created_at=_NOW,
            )
        )
        await session.flush()
        session.add(
            ReviewRevisionModel(
                id=revision_id,
                order_id=order_id,
                extraction_snapshot_id=snapshot_id,
                revision_number=1,
                payload={},
                changes=[],
                actor="reviewer",
                created_at=_NOW,
            )
        )
        await session.commit()
    await engine.dispose()
    return revision_id


async def _revision_exists(revision_id: object) -> bool:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            return (
                await connection.scalar(
                    select(ReviewRevisionModel.id).where(ReviewRevisionModel.id == revision_id)
                )
                == revision_id
            )
    finally:
        await engine.dispose()
