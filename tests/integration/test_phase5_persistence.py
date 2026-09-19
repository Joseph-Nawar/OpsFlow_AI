"""Real-PostgreSQL tests for the Phase 5 persistence primitives."""

import asyncio
import os
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from opsflow.settings import Settings

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_2_REVISION = "0002_phase2_persistence"
PHASE_5_REVISION = "0003_phase5_extraction_snapshots"
PHASE_2_TABLES = {
    "orders",
    "order_lines",
    "source_documents",
    "validation_issues",
    "audit_events",
    "order_creation_idempotency",
}


def test_phase5_migration_revision_chain_is_locked() -> None:
    migration = runpy.run_path(
        str(REPOSITORY_ROOT / "alembic/versions/0003_phase5_extraction_snapshots.py")
    )

    assert migration["revision"] == PHASE_5_REVISION
    assert migration["down_revision"] == PHASE_2_REVISION


def test_phase5_migration_preserves_phase2_data_and_downgrades_in_reverse_order() -> None:
    asyncio.run(_assert_migration_lifecycle())


def test_phase5_schema_has_exact_snapshot_envelope_and_named_constraints() -> None:
    asyncio.run(_assert_snapshot_schema())


def test_phase5_snapshot_constraints_reject_invalid_rows() -> None:
    asyncio.run(_assert_invalid_snapshot_rows_rejected())


def test_phase5_snapshot_identity_and_cascade_contract() -> None:
    asyncio.run(_assert_snapshot_identity_and_cascade())


async def _assert_migration_lifecycle() -> None:
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", PHASE_2_REVISION)

    order_id = uuid4()
    source_id = uuid4()
    await _insert_phase2_order_and_source(order_id, source_id)

    _run_alembic("upgrade", PHASE_5_REVISION)
    assert PHASE_5_REVISION in _run_alembic("current")

    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT state FROM orders WHERE id = :order_id"),
                    {"order_id": order_id},
                )
                == "RECEIVED"
            )
            assert (
                await connection.scalar(
                    text("SELECT id FROM source_documents WHERE id = :source_id"),
                    {"source_id": source_id},
                )
                == source_id
            )
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            assert "extraction_snapshots" in tables
    finally:
        await engine.dispose()

    _run_alembic("downgrade", PHASE_2_REVISION)
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            assert tables == PHASE_2_TABLES | {"alembic_version"}
            source_unique_names = await connection.run_sync(
                lambda sync_connection: {
                    constraint["name"]
                    for constraint in inspect(sync_connection).get_unique_constraints(
                        "source_documents"
                    )
                }
            )
            assert "uq_source_documents_id_order_id" not in source_unique_names
    finally:
        await engine.dispose()

    _run_alembic("upgrade", PHASE_5_REVISION)


async def _assert_snapshot_schema() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            assert tables == PHASE_2_TABLES | {"extraction_snapshots", "alembic_version"}

            columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"]: column
                    for column in inspect(sync_connection).get_columns("extraction_snapshots")
                }
            )
            assert set(columns) == {
                "id",
                "order_id",
                "source_document_id",
                "source_sha256",
                "source_document_type",
                "payload",
                "created_at",
            }
            assert columns["id"]["nullable"] is False
            assert columns["order_id"]["nullable"] is False
            assert columns["source_document_id"]["nullable"] is False
            assert columns["source_sha256"]["nullable"] is False
            assert columns["source_document_type"]["nullable"] is False
            assert columns["payload"]["nullable"] is False
            assert columns["created_at"]["nullable"] is False
            assert columns["id"]["default"] is None
            assert columns["created_at"]["default"] is None
            assert columns["id"]["type"].__class__.__name__ == "UUID"
            assert columns["source_sha256"]["type"].__class__.__name__ == "TEXT"
            assert columns["source_document_type"]["type"].__class__.__name__ == "TEXT"
            assert columns["payload"]["type"].__class__.__name__ == "JSONB"
            assert columns["created_at"]["type"].__class__.__name__ == "DateTime"
            assert columns["created_at"]["type"].timezone is True

            primary_key = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_pk_constraint(
                    "extraction_snapshots"
                )
            )
            assert primary_key["constrained_columns"] == ["id"]

            unique_constraints = await connection.run_sync(
                lambda sync_connection: {
                    (constraint["name"], tuple(constraint["column_names"]))
                    for constraint in inspect(sync_connection).get_unique_constraints(
                        "extraction_snapshots"
                    )
                }
            )
            assert unique_constraints == {
                ("uq_extraction_snapshots_order_source", ("order_id", "source_document_id"))
            }
            source_unique_constraints = await connection.run_sync(
                lambda sync_connection: {
                    (constraint["name"], tuple(constraint["column_names"]))
                    for constraint in inspect(sync_connection).get_unique_constraints(
                        "source_documents"
                    )
                }
            )
            assert ("uq_source_documents_id_order_id", ("id", "order_id")) in (
                source_unique_constraints
            )

            foreign_keys = await connection.run_sync(
                lambda sync_connection: [
                    (
                        tuple(foreign_key["constrained_columns"]),
                        foreign_key["referred_table"],
                        tuple(foreign_key["referred_columns"]),
                        foreign_key["options"]["ondelete"],
                    )
                    for foreign_key in inspect(sync_connection).get_foreign_keys(
                        "extraction_snapshots"
                    )
                ]
            )
            assert set(foreign_keys) == {
                (("order_id",), "orders", ("id",), "CASCADE"),
                (
                    ("source_document_id", "order_id"),
                    "source_documents",
                    ("id", "order_id"),
                    "CASCADE",
                ),
            }

            check_names = await connection.run_sync(
                lambda sync_connection: {
                    check["name"]
                    for check in inspect(sync_connection).get_check_constraints(
                        "extraction_snapshots"
                    )
                }
            )
            assert check_names == {
                "ck_extraction_snapshots_sha256",
                "ck_extraction_snapshots_document_type",
                "ck_extraction_snapshots_payload_object",
            }

            indexes = await connection.run_sync(
                lambda sync_connection: {
                    (index["name"], tuple(index["column_names"]), index["unique"])
                    for index in inspect(sync_connection).get_indexes("extraction_snapshots")
                }
            )
            assert indexes == {("ix_extraction_snapshots_source_sha256", ("source_sha256",), False)}
            assert all(
                tuple(column_name for column_name in unique_columns) != ("source_sha256",)
                for _, unique_columns in unique_constraints
            )
    finally:
        await engine.dispose()


async def _assert_invalid_snapshot_rows_rejected() -> None:
    order_id = uuid4()
    source_id = uuid4()
    await _insert_phase2_order_and_source(order_id, source_id)
    engine = create_async_engine(Settings().database_url)
    try:
        invalid_rows = (
            ("uppercase SHA", "A" * 64, "PDF", "{}"),
            ("non-hex SHA", "g" * 64, "PDF", "{}"),
            ("short SHA", "a" * 63, "PDF", "{}"),
            ("long SHA", "a" * 65, "PDF", "{}"),
            ("invalid document type", "a" * 64, "DOC", "{}"),
            ("non-object payload", "a" * 64, "PDF", "[]"),
        )
        for _, source_sha256, document_type, payload in invalid_rows:
            await _assert_snapshot_rejected(
                engine,
                order_id=order_id,
                source_document_id=source_id,
                source_sha256=source_sha256,
                document_type=document_type,
                payload=payload,
            )
    finally:
        await engine.dispose()


async def _assert_snapshot_identity_and_cascade() -> None:
    first_order_id = uuid4()
    first_source_id = uuid4()
    second_order_id = uuid4()
    second_source_id = uuid4()
    await _insert_phase2_order_and_source(first_order_id, first_source_id, "a" * 64)
    await _insert_phase2_order_and_source(second_order_id, second_source_id, "a" * 64)
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as connection:
            await _insert_snapshot(
                connection,
                first_order_id,
                first_source_id,
                "a" * 64,
            )
            await _insert_snapshot(
                connection,
                second_order_id,
                second_source_id,
                "a" * 64,
            )

        await _assert_snapshot_rejected(
            engine,
            order_id=first_order_id,
            source_document_id=first_source_id,
            source_sha256="a" * 64,
            document_type="PDF",
            payload="{}",
        )

        mismatch_source_id = uuid4()
        await _insert_phase2_order_and_source(first_order_id, mismatch_source_id, "b" * 64, 1)
        await _assert_snapshot_rejected(
            engine,
            order_id=second_order_id,
            source_document_id=mismatch_source_id,
            source_sha256="b" * 64,
            document_type="PDF",
            payload="{}",
        )

        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": first_order_id},
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM extraction_snapshots WHERE order_id = :order_id"),
                    {"order_id": first_order_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM source_documents WHERE order_id = :order_id"),
                    {"order_id": first_order_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM extraction_snapshots WHERE order_id = :order_id"),
                    {"order_id": second_order_id},
                )
                == 1
            )
    finally:
        await engine.dispose()


async def _insert_phase2_order_and_source(
    order_id: object,
    source_id: object,
    source_sha256: str = "a" * 64,
    position: int = 0,
) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO orders (id, state, failure_origin) "
                    "VALUES (:order_id, 'RECEIVED', NULL)"
                ),
                {"order_id": order_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO source_documents "
                    "(id, order_id, position, document_type, name, mime_type, sha256, metadata) "
                    "VALUES (:source_id, :order_id, :position, 'PDF', 'fixture.pdf', "
                    "'application/pdf', :source_sha256, '[]'::jsonb)"
                ),
                {
                    "source_id": source_id,
                    "order_id": order_id,
                    "position": position,
                    "source_sha256": source_sha256,
                },
            )
    finally:
        await engine.dispose()


async def _insert_snapshot(
    connection: object,
    order_id: object,
    source_document_id: object,
    source_sha256: str,
    document_type: str = "PDF",
    payload: str = "{}",
) -> None:
    await connection.execute(
        text(
            "INSERT INTO extraction_snapshots "
            "(id, order_id, source_document_id, source_sha256, "
            "source_document_type, payload, created_at) "
            "VALUES (:id, :order_id, :source_document_id, :source_sha256, :document_type, "
            "CAST(:payload AS jsonb), :created_at)"
        ),
        {
            "id": uuid4(),
            "order_id": order_id,
            "source_document_id": source_document_id,
            "source_sha256": source_sha256,
            "document_type": document_type,
            "payload": payload,
            "created_at": datetime(2030, 1, 1, tzinfo=UTC),
        },
    )


async def _assert_snapshot_rejected(
    engine: AsyncEngine,
    *,
    order_id: object,
    source_document_id: object,
    source_sha256: str,
    document_type: str,
    payload: str,
) -> None:
    with pytest.raises(DBAPIError):
        async with engine.begin() as connection:
            await _insert_snapshot(
                connection,
                order_id,
                source_document_id,
                source_sha256,
                document_type,
                payload,
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
