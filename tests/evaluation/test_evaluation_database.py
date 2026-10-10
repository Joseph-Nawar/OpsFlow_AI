from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from opsflow.evaluation.database import (
    EvaluationDatabaseConfig,
    EvaluationDatabaseSafetyError,
    assert_evaluation_database_isolated,
    confirm_current_migration_head,
    reset_evaluation_application_data,
)
from opsflow.persistence.models import (
    AuditEventModel,
    Base,
    ExtractionSnapshotModel,
    NotificationDeliveryModel,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    OrderSyncModel,
    ReviewRevisionModel,
    SourceDocumentModel,
    ValidationIssueModel,
)
from opsflow.settings import Settings

EXPECTED_HEAD = "0007_phase7_intake_ownership"
EVALUATION_URL = "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:55432/opsflow_evaluation"
NORMAL_URL = "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:5432/opsflow"
MIGRATION_URL = "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:5432/opsflow_migration_test"


def config_for(
    evaluation_url: str = EVALUATION_URL,
    normal_url: str = NORMAL_URL,
    migration_url: str | None = MIGRATION_URL,
) -> EvaluationDatabaseConfig:
    return EvaluationDatabaseConfig.from_environment(
        {"OPSFLOW_EVALUATION_DATABASE_URL": evaluation_url}, normal_url, migration_url
    )


def test_evaluation_config_parses_only_a_distinct_named_async_postgresql_target() -> None:
    config = config_for()

    assert config.evaluation_database_name == "opsflow_evaluation"
    assert config.url.get_backend_name() == "postgresql"
    assert config.url.drivername == "postgresql+asyncpg"
    assert_evaluation_database_isolated(config)


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"OPSFLOW_EVALUATION_DATABASE_URL": ""},
        {"OPSFLOW_EVALUATION_DATABASE_URL": "   "},
        {"OPSFLOW_EVALUATION_DATABASE_URL": "not-a-database-url"},
        {"OPSFLOW_EVALUATION_DATABASE_URL": "sqlite+aiosqlite:///evaluation.db"},
        {"OPSFLOW_EVALUATION_DATABASE_URL": "postgresql+asyncpg://opsflow:opsflow@localhost:5432/"},
        {"OPSFLOW_EVALUATION_DATABASE_URL": "postgresql+asyncpg://opsflow:opsflow@localhost:5432"},
    ],
)
def test_evaluation_config_fails_closed_on_missing_or_unprovable_identity(
    environment: dict[str, str],
) -> None:
    with pytest.raises(EvaluationDatabaseSafetyError):
        EvaluationDatabaseConfig.from_environment(environment, NORMAL_URL, MIGRATION_URL)


@pytest.mark.parametrize(
    "evaluation_url",
    [
        NORMAL_URL,
        "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:55432/opsflow",
        "postgresql+asyncpg://opsflow:opsflow@127.0.0.1:55432/opsflow_migration_test",
        "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow",
    ],
)
def test_evaluation_config_rejects_normal_migration_and_host_alias_targets(
    evaluation_url: str,
) -> None:
    with pytest.raises(EvaluationDatabaseSafetyError):
        config_for(evaluation_url)


def test_migration_database_cannot_be_omitted_when_configured() -> None:
    with pytest.raises(EvaluationDatabaseSafetyError):
        EvaluationDatabaseConfig.from_environment(
            {"OPSFLOW_EVALUATION_DATABASE_URL": EVALUATION_URL},
            NORMAL_URL,
            "postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_evaluation",
        )


def test_reset_rejects_engine_identity_mismatch_before_connecting() -> None:
    class NeverConnectEngine:
        url: URL = make_url(NORMAL_URL)

        def begin(self):
            pytest.fail("database guard must run before opening a connection")

    with pytest.raises(EvaluationDatabaseSafetyError):
        asyncio.run(reset_evaluation_application_data(config_for(), NeverConnectEngine()))  # type: ignore[arg-type]


def test_current_migration_revision_matches_the_repository_head() -> None:
    database_url = os.environ.get("OPSFLOW_EVALUATION_DATABASE_URL")
    if not database_url:
        pytest.skip("guarded evaluation PostgreSQL database is not configured")
    config = Config("alembic.ini")
    confirm_current_migration_head(config, EXPECTED_HEAD)


def _evaluation_config_from_environment() -> EvaluationDatabaseConfig:
    return EvaluationDatabaseConfig.from_environment(
        os.environ,
        Settings().database_url,
        os.environ.get("OPSFLOW_MIGRATION_TEST_DATABASE_URL"),
    )


@pytest.fixture
def evaluation_engine() -> Iterator[AsyncEngine]:
    if not os.environ.get("OPSFLOW_EVALUATION_DATABASE_URL"):
        pytest.skip("guarded evaluation PostgreSQL database is not configured")
    config = _evaluation_config_from_environment()
    engine = create_async_engine(config.evaluation_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        asyncio.run(engine.dispose())


async def _seed_complete_application_graph(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    order_id = uuid4()
    source_id = uuid4()
    snapshot_id = uuid4()
    event_id = uuid4()
    now = datetime(2026, 10, 10, tzinfo=UTC)
    sha = "a" * 64
    async with sessions() as session, session.begin():
        session.add(
            OrderModel(
                id=order_id,
                customer_reference="EVAL-CUSTOMER",
                po_number="EVAL-PO",
                state="READY_FOR_APPROVAL",
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            OrderLineModel(
                order_id=order_id,
                position=0,
                sku="EVAL-SKU",
                description="evaluation fixture",
                quantity=Decimal("1"),
                submitted_price=Decimal("10"),
                trusted_catalogue_price=Decimal("10"),
            )
        )
        session.add(
            SourceDocumentModel(
                id=source_id,
                order_id=order_id,
                position=0,
                document_type="EMAIL_BODY",
                name="evaluation.txt",
                mime_type="text/plain",
                sha256=sha,
                message_id=None,
                storage_reference=None,
                metadata_=[],
            )
        )
        await session.flush()
        session.add(
            ValidationIssueModel(
                order_id=order_id,
                position=0,
                rule_code="EVALUATION_FIXTURE",
                severity="INFO",
                field="po_number",
                expected=None,
                actual=None,
                explanation="evaluation fixture",
            )
        )
        session.add(
            AuditEventModel(
                id=event_id,
                order_id=order_id,
                event_type="ORDER_READY_FOR_APPROVAL",
                actor="evaluation-test",
                occurred_at=now,
                description="evaluation fixture",
            )
        )
        await session.flush()
        session.add(
            OrderCreationIdempotencyModel(
                idempotency_key=f"evaluation-{order_id}",
                request_fingerprint="b" * 64,
                order_id=order_id,
                created_at=now,
            )
        )
        session.add(
            ExtractionSnapshotModel(
                id=snapshot_id,
                order_id=order_id,
                source_document_id=source_id,
                source_sha256=sha,
                source_document_type="EMAIL_BODY",
                payload={},
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            ReviewRevisionModel(
                id=uuid4(),
                order_id=order_id,
                extraction_snapshot_id=snapshot_id,
                revision_number=1,
                payload={},
                changes=[],
                actor="evaluation-test",
                created_at=now,
            )
        )
        session.add(
            NotificationDeliveryModel(
                id=uuid4(),
                order_id=order_id,
                trigger_audit_event_id=event_id,
                channel="SLACK",
                kind="APPROVAL_READY",
                payload={},
                status="PENDING",
                attempt_count=0,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(OrderSyncModel(order_id=order_id))


async def _application_table_counts(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with sessions() as session:
        counts = {
            name: int(
                await session.scalar(select(func.count()).select_from(Base.metadata.tables[name]))
                or 0
            )
            for name in Base.metadata.tables
        }
    return counts


def test_guarded_reset_clears_only_the_application_graph_and_preserves_migrations(
    evaluation_engine: AsyncEngine,
) -> None:
    config = _evaluation_config_from_environment()
    sessions = async_sessionmaker(evaluation_engine, expire_on_commit=False)

    async def reset_and_count() -> tuple[dict[str, int], dict[str, int]]:
        await reset_evaluation_application_data(config, evaluation_engine)
        empty = await _application_table_counts(sessions)
        await _seed_complete_application_graph(sessions)
        seeded = await _application_table_counts(sessions)
        await reset_evaluation_application_data(config, evaluation_engine)
        cleared = await _application_table_counts(sessions)
        return seeded, {name: cleared[name] for name in cleared if empty[name] == 0}

    seeded, cleared = asyncio.run(reset_and_count())

    assert set(seeded) == set(Base.metadata.tables)
    assert all(count == 1 for count in seeded.values())
    assert all(count == 0 for count in cleared.values())
    confirm_current_migration_head(Config("alembic.ini"), EXPECTED_HEAD)


def test_repeated_guarded_resets_produce_equivalent_clean_application_state(
    evaluation_engine: AsyncEngine,
) -> None:
    config = _evaluation_config_from_environment()
    sessions = async_sessionmaker(evaluation_engine, expire_on_commit=False)

    async def reset_twice() -> tuple[dict[str, int], dict[str, int]]:
        await reset_evaluation_application_data(config, evaluation_engine)
        first = await _application_table_counts(sessions)
        await reset_evaluation_application_data(config, evaluation_engine)
        second = await _application_table_counts(sessions)
        return first, second

    first, second = asyncio.run(reset_twice())
    assert first == second
    assert all(count == 0 for count in first.values())
