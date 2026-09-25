"""Real-PostgreSQL tests for Phase 6 immutable review revisions."""

import asyncio
import os
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import opsflow.persistence.repositories as repositories_module
from opsflow.domain import SourceDocumentType
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.persistence.mappers import extraction_draft_to_payload
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderModel,
    ReviewRevisionModel,
    SourceDocumentModel,
)
from opsflow.persistence.repositories import (
    get_latest_audit_event_id,
    get_latest_review_revision,
    get_review_revision_history,
    insert_review_revision,
)
from opsflow.review import ReviewChange, ReviewDraft, ReviewLine, ReviewRevision
from opsflow.settings import Settings

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_5_REVISION = "0003_phase5_extraction_snapshots"
PHASE_6_REVISION = "0004_phase6_review_revisions"
CURRENT_HEAD_REVISION = "0005_phase8_notification_deliveries"


def test_phase6_migration_revision_chain_is_locked() -> None:
    migration = runpy.run_path(
        str(REPOSITORY_ROOT / "alembic/versions/0004_phase6_review_revisions.py")
    )

    assert migration["revision"] == PHASE_6_REVISION
    assert migration["down_revision"] == PHASE_5_REVISION


def test_phase6_migration_upgrade_downgrade_and_reupgrade_preserve_phase5_data() -> None:
    asyncio.run(_assert_migration_lifecycle())


def test_review_revision_repository_is_append_only_and_transaction_owned() -> None:
    assert not hasattr(repositories_module, "update_review_revision")
    assert not hasattr(repositories_module, "delete_review_revision")
    asyncio.run(_assert_review_revision_repository())


async def _assert_migration_lifecycle() -> None:
    _run_alembic("downgrade", PHASE_5_REVISION)
    order_id = uuid4()
    source_id = uuid4()
    snapshot_id = uuid4()
    await _insert_phase5_snapshot(order_id, source_id, snapshot_id)

    _run_alembic("upgrade", "head")
    assert CURRENT_HEAD_REVISION in _run_alembic("current")
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(ExtractionSnapshotModel.id).where(
                        ExtractionSnapshotModel.id == snapshot_id
                    )
                )
                == snapshot_id
            )
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            assert "review_revisions" in table_names
            snapshot_uniques = await connection.run_sync(
                lambda sync_connection: {
                    constraint["name"]
                    for constraint in inspect(sync_connection).get_unique_constraints(
                        "extraction_snapshots"
                    )
                }
            )
            assert "uq_extraction_snapshots_id_order_id" in snapshot_uniques
    finally:
        await engine.dispose()

    _run_alembic("downgrade", PHASE_5_REVISION)
    assert PHASE_5_REVISION in _run_alembic("current")
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(ExtractionSnapshotModel.id).where(
                        ExtractionSnapshotModel.id == snapshot_id
                    )
                )
                == snapshot_id
            )
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            assert "review_revisions" not in table_names
            snapshot_uniques = await connection.run_sync(
                lambda sync_connection: {
                    constraint["name"]
                    for constraint in inspect(sync_connection).get_unique_constraints(
                        "extraction_snapshots"
                    )
                }
            )
            assert "uq_extraction_snapshots_id_order_id" not in snapshot_uniques
    finally:
        await engine.dispose()

    _run_alembic("upgrade", "head")
    assert CURRENT_HEAD_REVISION in _run_alembic("current")


async def _assert_review_revision_repository() -> None:
    _run_alembic("upgrade", "head")
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    order_a, snapshot_a = uuid4(), uuid4()
    order_b, snapshot_b = uuid4(), uuid4()
    source_a, source_b = uuid4(), uuid4()
    await _insert_order_snapshot_graph(order_a, source_a, snapshot_a)
    await _insert_order_snapshot_graph(order_b, source_b, snapshot_b)

    first_time = datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    second_time = datetime(2026, 9, 19, 11, 0, tzinfo=UTC)
    audit_ids = sorted((uuid4(), uuid4()))
    latest_time_ids = sorted((uuid4(), uuid4()))
    async with session_factory() as session:
        session.add_all(
            [
                AuditEventModel(
                    id=audit_ids[0],
                    order_id=order_a,
                    event_type="REVIEW_RECORDED",
                    actor="reviewer",
                    occurred_at=first_time,
                    description="first",
                ),
                AuditEventModel(
                    id=audit_ids[1],
                    order_id=order_a,
                    event_type="REVIEW_REVALIDATED",
                    actor="reviewer",
                    occurred_at=first_time,
                    description="tie resolved by UUID",
                ),
                AuditEventModel(
                    id=latest_time_ids[0],
                    order_id=order_a,
                    event_type="ORDER_READY",
                    actor="reviewer",
                    occurred_at=second_time,
                    description="later, earlier id",
                ),
                AuditEventModel(
                    id=latest_time_ids[1],
                    order_id=order_a,
                    event_type="ORDER_READY",
                    actor="reviewer",
                    occurred_at=second_time,
                    description="later, greater id",
                ),
            ]
        )
        await session.commit()

    revision_one = _revision(order_a, snapshot_a, 1, "first")
    revision_two = _revision(order_a, snapshot_a, 2, "second")
    async with session_factory() as session:
        await insert_review_revision(session, revision_one)
        assert session.in_transaction()
        await session.rollback()
    async with session_factory() as session:
        assert await get_latest_review_revision(session, order_a) is None
        await insert_review_revision(session, revision_one)
        await insert_review_revision(session, revision_two)
        await session.commit()

    async with session_factory() as session:
        latest = await get_latest_review_revision(session, order_a)
        history = await get_review_revision_history(session, order_a)
        latest_audit_id = await get_latest_audit_event_id(session, order_a)
        assert latest == revision_two
        assert history == (revision_one, revision_two)
        assert latest_audit_id == latest_time_ids[1]
        assert await get_latest_review_revision(session, order_b) is None

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await insert_review_revision(session, _revision(order_a, snapshot_a, 2, "duplicate"))
        await session.rollback()

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await insert_review_revision(session, _revision(order_a, snapshot_b, 3, "cross-owner"))
        await session.rollback()

    async with session_factory() as session:
        await session.execute(delete(OrderModel).where(OrderModel.id == order_a))
        await session.commit()
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ReviewRevisionModel)
                .where(ReviewRevisionModel.order_id == order_a)
            )
            == 0
        )
        assert await get_latest_audit_event_id(session, order_a) is None

    await engine.dispose()


async def _insert_phase5_snapshot(order_id: UUID, source_id: UUID, snapshot_id: UUID) -> None:
    await _insert_order_snapshot_graph(order_id, source_id, snapshot_id)


async def _insert_order_snapshot_graph(order_id: UUID, source_id: UUID, snapshot_id: UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                OrderModel.__table__.insert().values(
                    id=order_id,
                    customer_reference=None,
                    po_number=None,
                    order_date=None,
                    requested_delivery_date=None,
                    currency=None,
                    state="NEEDS_REVIEW",
                    failure_origin=None,
                    created_at=datetime(2026, 9, 19, tzinfo=UTC),
                )
            )
            await connection.execute(
                SourceDocumentModel.__table__.insert().values(
                    id=source_id,
                    order_id=order_id,
                    position=0,
                    document_type="PDF",
                    name="order.pdf",
                    mime_type="application/pdf",
                    sha256="a" * 64,
                    message_id=None,
                    storage_reference=None,
                    metadata=[],
                )
            )
            await connection.execute(
                ExtractionSnapshotModel.__table__.insert().values(
                    id=snapshot_id,
                    order_id=order_id,
                    source_document_id=source_id,
                    source_sha256="a" * 64,
                    source_document_type="PDF",
                    payload=extraction_draft_to_payload(_extraction_draft()),
                    created_at=datetime(2026, 9, 19, tzinfo=UTC),
                )
            )
    finally:
        await engine.dispose()


def _extraction_draft() -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256="a" * 64,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme",
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=None,
        requested_delivery_date=None,
        currency="USD",
        lines=(ExtractedLine("SKU-1", "Widget", Decimal("1"), Decimal("10")),),
        notes=None,
        evidence=(),
    )


def _revision(
    order_id: UUID,
    snapshot_id: UUID,
    revision_number: int,
    actor: str,
) -> ReviewRevision:
    line = ReviewLine("SKU-1", "Widget", Decimal("1"), Decimal("10"))
    draft = ReviewDraft("Acme", "CUST-1", "PO-1", None, None, "USD", (line,))
    return ReviewRevision(
        id=uuid4(),
        order_id=order_id,
        extraction_snapshot_id=snapshot_id,
        revision_number=revision_number,
        payload=draft,
        changes=(ReviewChange("customer_name", "Old Acme", "Acme"),),
        actor=actor,
        created_at=datetime(2026, 9, 19, 12, revision_number, tzinfo=UTC),
    )


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
