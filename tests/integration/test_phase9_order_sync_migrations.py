"""PostgreSQL migration and constraint tests for durable Phase 9 sync rows."""

import asyncio
import os
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from opsflow.persistence.models import (
    AuditEventModel,
    NotificationDeliveryModel,
    OrderModel,
    OrderSyncModel,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_8_REVISION = "0005_phase8_notification_deliveries"
PHASE_9_REVISION = "0006_phase9_order_syncs"
_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def test_phase9_migration_revision_is_child_of_phase8_head() -> None:
    migration = runpy.run_path(str(REPOSITORY_ROOT / "alembic/versions/0006_phase9_order_syncs.py"))

    assert migration["revision"] == PHASE_9_REVISION
    assert migration["down_revision"] == PHASE_8_REVISION


def test_clean_upgrade_and_order_sync_schema_constraints(
    migration_test_database_url: str,
) -> None:
    _run_alembic(migration_test_database_url, "downgrade", "base")
    _run_alembic(migration_test_database_url, "upgrade", "head")
    assert PHASE_9_REVISION in _run_alembic(migration_test_database_url, "current")
    asyncio.run(_assert_schema_and_constraints(migration_test_database_url))


def test_incremental_phase8_upgrade_preserves_existing_business_data(
    migration_test_database_url: str,
) -> None:
    _run_alembic(migration_test_database_url, "downgrade", "base")
    _run_alembic(migration_test_database_url, "upgrade", PHASE_8_REVISION)
    order_id, event_id = asyncio.run(_insert_phase8_rows(migration_test_database_url))

    _run_alembic(migration_test_database_url, "upgrade", PHASE_9_REVISION)
    assert PHASE_9_REVISION in _run_alembic(migration_test_database_url, "current")
    assert asyncio.run(_phase8_rows_exist(migration_test_database_url, order_id, event_id))

    # Downgrade is intentionally limited to the isolated disposable migration database.
    _run_alembic(migration_test_database_url, "downgrade", PHASE_8_REVISION)
    assert PHASE_8_REVISION in _run_alembic(migration_test_database_url, "current")
    assert asyncio.run(_phase8_rows_exist(migration_test_database_url, order_id, event_id))
    _run_alembic(migration_test_database_url, "upgrade", "head")
    assert asyncio.run(_phase8_rows_exist(migration_test_database_url, order_id, event_id))


def _run_alembic(database_url: str, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["OPSFLOW_DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return f"{result.stdout}\n{result.stderr}"


async def _assert_schema_and_constraints(database_url: str) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            assert "order_syncs" in await connection.run_sync(
                lambda sync: set(inspect(sync).get_table_names())
            )
            columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("order_syncs")}
            )
            assert columns == {
                "order_id",
                "claim_token",
                "claim_expires_at",
                "attempt_count",
                "retry_generation",
                "next_attempt_at",
                "odoo_sale_order_id",
                "odoo_sale_order_name",
                "hubspot_company_id",
                "hubspot_deal_id",
                "hubspot_association_confirmed_at",
                "in_flight_step",
                "last_failure_step",
                "last_failure_code",
                "last_attempt_at",
                "created_at",
                "updated_at",
            }
            checks = await connection.run_sync(
                lambda sync: {
                    check["name"] for check in inspect(sync).get_check_constraints("order_syncs")
                }
            )
            assert checks == {
                "ck_order_syncs_claim_pair",
                "ck_order_syncs_attempt_count",
                "ck_order_syncs_retry_generation",
                "ck_order_syncs_in_flight_step",
                "ck_order_syncs_failure_step",
                "ck_order_syncs_failure_code",
                "ck_order_syncs_failure_pair",
                "ck_order_syncs_odoo_receipt_pair",
                "ck_order_syncs_hubspot_company_id",
                "ck_order_syncs_hubspot_deal_id",
                "ck_order_syncs_association_receipt",
            }
            primary_key = await connection.run_sync(
                lambda sync: inspect(sync).get_pk_constraint("order_syncs")
            )
            assert primary_key["constrained_columns"] == ["order_id"]
            assert primary_key["name"] == "pk_order_syncs"
            foreign_keys = await connection.run_sync(
                lambda sync: inspect(sync).get_foreign_keys("order_syncs")
            )
            assert len(foreign_keys) == 1
            assert foreign_keys[0]["constrained_columns"] == ["order_id"]
            assert foreign_keys[0]["referred_table"] == "orders"
            assert foreign_keys[0]["options"].get("ondelete") == "CASCADE"
            indexes = await connection.run_sync(
                lambda sync: {
                    index["name"]: index for index in inspect(sync).get_indexes("order_syncs")
                }
            )
            assert set(indexes) == {
                "uq_order_syncs_odoo_sale_order_id",
                "uq_order_syncs_hubspot_deal_id",
                "ix_order_syncs_claim_eligibility",
            }
            assert indexes["uq_order_syncs_odoo_sale_order_id"]["unique"] is True
            assert indexes["uq_order_syncs_hubspot_deal_id"]["unique"] is True
            assert indexes["ix_order_syncs_claim_eligibility"]["unique"] is False
            assert all(
                indexes[name].get("dialect_options", {}).get("postgresql_where")
                for name in (
                    "uq_order_syncs_odoo_sale_order_id",
                    "uq_order_syncs_hubspot_deal_id",
                )
            )
            assert all(
                "hubspot_company_id" not in index["column_names"] for index in indexes.values()
            )

        order_id = uuid4()
        async with session_factory() as session:
            session.add(OrderModel(id=order_id, state="APPROVED", created_at=_NOW))
            await session.flush()
            # Retry generations have no artificial three-generation ceiling.
            session.add(_sync_row(order_id, retry_generation=10_000))
            await session.commit()

        for overrides in (
            {"attempt_count": -1},
            {"attempt_count": 4},
            {"retry_generation": -1},
            {"claim_token": uuid4()},
            {"in_flight_step": "RAW_PROVIDER_METHOD"},
            {
                "last_failure_step": "HUBSPOT_DEAL",
                "last_failure_code": "RAW_PROVIDER_ERROR",
            },
            {
                "last_failure_step": "RAW_PROVIDER_METHOD",
                "last_failure_code": "PROVIDER_UNAVAILABLE",
            },
            {"odoo_sale_order_id": 9002},
            {"odoo_sale_order_name": "S09002"},
            {"odoo_sale_order_id": 0, "odoo_sale_order_name": "S00000"},
        ):
            invalid_order_id = uuid4()
            async with session_factory() as session:
                session.add(OrderModel(id=invalid_order_id, state="APPROVED", created_at=_NOW))
                await session.flush()
                session.add(_sync_row(invalid_order_id, **overrides))
                with pytest.raises(DBAPIError):
                    await session.flush()
                await session.rollback()

        await _assert_receipt_uniqueness(session_factory)
    finally:
        await engine.dispose()


async def _assert_receipt_uniqueness(session_factory: async_sessionmaker) -> None:
    first_order, same_company_order, duplicate_odoo_order, duplicate_deal_order = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    async with session_factory() as session:
        session.add_all(
            [
                OrderModel(id=order_id, state="SYNCING", created_at=_NOW)
                for order_id in (
                    first_order,
                    same_company_order,
                    duplicate_odoo_order,
                    duplicate_deal_order,
                )
            ]
        )
        await session.flush()
        session.add(
            _sync_row(
                first_order,
                odoo_sale_order_id=9001,
                odoo_sale_order_name="S009001",
                hubspot_company_id="shared-company",
                hubspot_deal_id="deal-9001",
            )
        )
        session.add(_sync_row(same_company_order, hubspot_company_id="shared-company"))
        await session.commit()

    async with session_factory() as session:
        session.add(
            _sync_row(
                duplicate_odoo_order,
                odoo_sale_order_id=9001,
                odoo_sale_order_name="S009001",
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()

    async with session_factory() as session:
        session.add(_sync_row(duplicate_deal_order, hubspot_deal_id="deal-9001"))
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()


def _sync_row(order_id: object, **overrides: object) -> OrderSyncModel:
    values: dict[str, object] = {
        "order_id": order_id,
        "claim_token": None,
        "claim_expires_at": None,
        "attempt_count": 0,
        "retry_generation": 0,
        "next_attempt_at": _NOW,
        "odoo_sale_order_id": None,
        "odoo_sale_order_name": None,
        "hubspot_company_id": None,
        "hubspot_deal_id": None,
        "hubspot_association_confirmed_at": None,
        "in_flight_step": None,
        "last_failure_step": None,
        "last_failure_code": None,
        "last_attempt_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return OrderSyncModel(**values)


async def _insert_phase8_rows(database_url: str) -> tuple[object, object]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    order_id, event_id, delivery_id = uuid4(), uuid4(), uuid4()
    try:
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
            await session.flush()
            session.add(
                NotificationDeliveryModel(
                    id=delivery_id,
                    order_id=order_id,
                    trigger_audit_event_id=event_id,
                    channel="SLACK",
                    kind="REVIEW_REQUIRED",
                    payload={"text": "Review is required."},
                    status="PENDING",
                    attempt_count=0,
                    claim_token=None,
                    claim_expires_at=None,
                    next_attempt_at=_NOW,
                    provider_reference=None,
                    last_failure_code=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return order_id, event_id


async def _phase8_rows_exist(database_url: str, order_id: object, event_id: object) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            order_exists = await connection.scalar(
                select(OrderModel.id).where(OrderModel.id == order_id)
            )
            event_exists = await connection.scalar(
                select(AuditEventModel.id).where(AuditEventModel.id == event_id)
            )
            delivery_exists = await connection.scalar(
                select(NotificationDeliveryModel.order_id).where(
                    NotificationDeliveryModel.order_id == order_id,
                    NotificationDeliveryModel.trigger_audit_event_id == event_id,
                )
            )
            return (
                order_exists == order_id
                and event_exists == event_id
                and delivery_exists == order_id
            )
    finally:
        await engine.dispose()
