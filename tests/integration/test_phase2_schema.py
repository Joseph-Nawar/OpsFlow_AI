"""Real-PostgreSQL schema and defense-in-depth constraint tests for Phase 2."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from opsflow.settings import Settings

PHASE_2_TABLES = {
    "orders",
    "order_lines",
    "source_documents",
    "validation_issues",
    "audit_events",
    "order_creation_idempotency",
}


def test_phase2_schema_has_exact_tables_constraints_and_indexes() -> None:
    asyncio.run(_assert_schema())


def test_postgresql_rejects_invalid_phase2_rows() -> None:
    asyncio.run(_assert_invalid_rows_rejected())


async def _assert_schema() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            assert tables == PHASE_2_TABLES | {"alembic_version"}

            foreign_keys = await connection.run_sync(_foreign_keys)
            assert foreign_keys == {
                ("order_lines", "order_id", "orders.id", "CASCADE"),
                ("source_documents", "order_id", "orders.id", "CASCADE"),
                ("validation_issues", "order_id", "orders.id", "CASCADE"),
                ("audit_events", "order_id", "orders.id", "CASCADE"),
                ("order_creation_idempotency", "order_id", "orders.id", "RESTRICT"),
            }

            primary_keys, unique_constraints, indexes = await connection.run_sync(
                _key_constraints_and_indexes
            )
            assert primary_keys == {
                "orders": ("id",),
                "order_lines": ("id",),
                "source_documents": ("id",),
                "validation_issues": ("order_id", "position"),
                "audit_events": ("id",),
                "order_creation_idempotency": ("idempotency_key",),
            }
            assert unique_constraints == {
                ("order_lines", "uq_order_lines_order_position", ("order_id", "position")),
                (
                    "source_documents",
                    "uq_source_documents_order_position",
                    ("order_id", "position"),
                ),
                (
                    "order_creation_idempotency",
                    "uq_order_creation_idempotency_order_id",
                    ("order_id",),
                ),
            }
            assert indexes == {
                (
                    "audit_events",
                    "ix_audit_events_order_occurred_at_id",
                    (
                        "order_id",
                        "occurred_at",
                        "id",
                    ),
                ),
            }

            check_names = await connection.run_sync(_check_names)
            assert check_names == {
                "ck_orders_state",
                "ck_orders_currency",
                "ck_orders_failure_origin",
                "ck_order_lines_position",
                "ck_order_lines_quantity",
                "ck_order_lines_submitted_price",
                "ck_order_lines_trusted_catalogue_price",
                "ck_source_documents_position",
                "ck_source_documents_document_type",
                "ck_source_documents_sha256",
                "ck_source_documents_metadata_array",
                "ck_validation_issues_position",
                "ck_validation_issues_severity",
                "ck_order_creation_idempotency_key",
                "ck_order_creation_idempotency_fingerprint",
            }
    finally:
        await engine.dispose()


def _foreign_keys(connection: object) -> set[tuple[str, str, str, str]]:
    inspector = inspect(connection)
    result: set[tuple[str, str, str, str]] = set()
    for table_name in PHASE_2_TABLES:
        for foreign_key in inspector.get_foreign_keys(table_name):
            result.add(
                (
                    table_name,
                    foreign_key["constrained_columns"][0],
                    f"{foreign_key['referred_table']}.{foreign_key['referred_columns'][0]}",
                    foreign_key["options"]["ondelete"],
                )
            )
    return result


def _key_constraints_and_indexes(
    connection: object,
) -> tuple[
    dict[str, tuple[str, ...]],
    set[tuple[str, str, tuple[str, ...]]],
    set[tuple[str, str, tuple[str, ...]]],
]:
    inspector = inspect(connection)
    primary_keys = {
        table_name: tuple(inspector.get_pk_constraint(table_name)["constrained_columns"])
        for table_name in PHASE_2_TABLES
    }
    unique_constraints = {
        (table_name, constraint["name"], tuple(constraint["column_names"]))
        for table_name in PHASE_2_TABLES
        for constraint in inspector.get_unique_constraints(table_name)
    }
    indexes = {
        (table_name, index["name"], tuple(index["column_names"]))
        for table_name in PHASE_2_TABLES
        for index in inspector.get_indexes(table_name)
        if not index["unique"]
    }
    return primary_keys, unique_constraints, indexes


def _check_names(connection: object) -> set[str]:
    inspector = inspect(connection)
    return {
        check["name"]
        for table_name in PHASE_2_TABLES
        for check in inspector.get_check_constraints(table_name)
    }


async def _assert_invalid_rows_rejected() -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        order_id = uuid4()
        await _execute(
            engine,
            text("INSERT INTO orders (id, state, failure_origin) VALUES (:id, 'RECEIVED', NULL)"),
            {"id": order_id},
        )

        invalid_order_rows = (
            ("unknown state", "INSERT INTO orders (id, state) VALUES (:id, 'UNKNOWN')", {}),
            (
                "failed state with NULL origin",
                "INSERT INTO orders (id, state, failure_origin) VALUES (:id, 'FAILED_FINAL', NULL)",
                {},
            ),
            (
                "invalid failure origin",
                "INSERT INTO orders (id, state, failure_origin) "
                "VALUES (:id, 'FAILED_FINAL', 'COMPLETED')",
                {},
            ),
        )
        for _, statement, parameters in invalid_order_rows:
            await _assert_rejected(engine, text(statement), {"id": uuid4(), **parameters})

        invalid_line_rows = (
            ("zero quantity", "quantity", 0),
            ("negative quantity", "quantity", -1),
        )
        for _, _, value in invalid_line_rows:
            line_id = uuid4()
            await _assert_rejected(
                engine,
                text(
                    "INSERT INTO order_lines (id, order_id, position, sku, quantity) "
                    "VALUES (:id, :order_id, 0, 'SKU', :value)"
                ),
                {"id": line_id, "order_id": order_id, "value": value},
            )

        for column_name in ("submitted_price", "trusted_catalogue_price"):
            await _assert_rejected(
                engine,
                text(
                    f"INSERT INTO order_lines "
                    f"(id, order_id, position, sku, quantity, {column_name}) "
                    "VALUES (:id, :order_id, 0, 'SKU', 1, :value)"
                ),
                {"id": uuid4(), "order_id": order_id, "value": -1},
            )

        await _assert_rejected(
            engine,
            text(
                "INSERT INTO order_lines "
                "(id, order_id, position, sku, quantity) "
                "VALUES (:id, :order_id, 0, 'SKU', 1), "
                "(:second_id, :order_id, 0, 'SKU', 1)"
            ),
            {"id": uuid4(), "second_id": uuid4(), "order_id": order_id},
        )
        await _assert_rejected(
            engine,
            text(
                "INSERT INTO order_lines "
                "(id, order_id, position, sku, quantity) "
                "VALUES (:id, :orphan_id, 0, 'SKU', 1)"
            ),
            {"id": uuid4(), "orphan_id": uuid4()},
        )
        await _assert_rejected(
            engine,
            text(
                "INSERT INTO source_documents "
                "(id, order_id, position, document_type, name, mime_type, sha256, metadata) "
                "VALUES (:id, :order_id, 0, 'DOC', 'name', 'text/plain', :sha256, '[]')"
            ),
            {"id": uuid4(), "order_id": order_id, "sha256": "a" * 64},
        )
        await _assert_rejected(
            engine,
            text(
                "INSERT INTO validation_issues "
                "(order_id, position, rule_code, severity, explanation) "
                "VALUES (:order_id, 0, 'RULE', 'CRITICAL', 'explanation')"
            ),
            {"order_id": order_id},
        )
    finally:
        await engine.dispose()


async def _execute(engine: AsyncEngine, statement: object, parameters: dict[str, object]) -> None:
    async with engine.begin() as connection:
        await connection.execute(statement, parameters)


async def _assert_rejected(
    engine: AsyncEngine,
    statement: object,
    parameters: dict[str, object],
) -> None:
    with pytest.raises(DBAPIError):
        async with engine.begin() as connection:
            await connection.execute(statement, parameters)
