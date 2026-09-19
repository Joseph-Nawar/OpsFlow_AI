"""Real-PostgreSQL tests for the Phase 5 persistence primitives."""

import asyncio
import os
import runpy
import subprocess
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import DateTime, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

import opsflow.persistence.repositories as repositories_module
from opsflow.domain import (
    Order,
    OrderLine,
    OrderState,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.persistence.mappers import PersistedExtractionSnapshot
from opsflow.persistence.models import OrderModel, ValidationIssueModel
from opsflow.persistence.repositories import (
    build_validation_facts,
    get_extraction_snapshot,
    get_order,
    get_order_for_update,
    has_customer_po_duplicate,
    has_processed_source_sha,
    insert_extraction_snapshot,
    insert_order_graph,
    replace_order_graph,
    replace_validation_issues,
    update_order_snapshot,
)
from opsflow.settings import Settings
from opsflow.validation import ValidationFacts

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


def test_snapshot_repository_round_trip_is_transaction_owned() -> None:
    asyncio.run(_assert_snapshot_repository_round_trip())


def test_snapshot_repository_exposes_insert_and_read_only() -> None:
    assert not hasattr(repositories_module, "update_extraction_snapshot")
    assert not hasattr(repositories_module, "delete_extraction_snapshot")


def test_customer_po_repository_uses_exact_identity_and_current_order_exclusion() -> None:
    asyncio.run(_assert_customer_po_repository())


def test_processed_sha_repository_excludes_only_the_current_pair() -> None:
    asyncio.run(_assert_processed_sha_repository())


def test_build_validation_facts_keeps_local_facts_immutable_and_runs_sha_lookup() -> None:
    asyncio.run(_assert_build_validation_facts())


def test_validation_issue_replacement_is_ordered_and_transaction_owned() -> None:
    asyncio.run(_assert_validation_issue_replacement())


def test_locked_order_read_preserves_normal_order_read_behavior() -> None:
    asyncio.run(_assert_locked_order_read())


def test_order_snapshot_and_graph_replacement_preserve_source_documents() -> None:
    asyncio.run(_assert_order_snapshot_and_graph_replacement())


def test_phase5_repository_writes_rollback_without_caller_commit() -> None:
    asyncio.run(_assert_repository_rollback())


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
            assert isinstance(columns["created_at"]["type"], DateTime)
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
                    if not index["unique"]
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
        await _insert_phase2_order_and_source(uuid4(), mismatch_source_id, "b" * 64, 1)
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


async def _assert_snapshot_repository_round_trip() -> None:
    order, source_document = _repository_order()
    snapshot = _repository_snapshot(order.id, source_document.id, "a" * 64)
    other_order, other_source_document = _repository_order(source_hashes=("b" * 64,))
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, datetime(2030, 1, 2, tzinfo=UTC))
            await insert_order_graph(session, other_order, datetime(2030, 1, 2, tzinfo=UTC))
            await session.commit()
            await insert_extraction_snapshot(session, snapshot)
            assert session.in_transaction()
            await session.commit()

            assert await get_extraction_snapshot(session, order.id, source_document.id) == snapshot
            assert await get_extraction_snapshot(session, order.id, uuid4()) is None

            with pytest.raises(IntegrityError):
                await insert_extraction_snapshot(session, snapshot)
            await session.rollback()

            mismatched = _repository_snapshot(order.id, other_source_document.id, "b" * 64)
            with pytest.raises(IntegrityError):
                await insert_extraction_snapshot(session, mismatched)
            await session.rollback()
    finally:
        await engine.dispose()


async def _assert_customer_po_repository() -> None:
    current, _ = _repository_order(customer_reference="CUST-1", po_number="PO-1")
    matching, _ = _repository_order(customer_reference="CUST-1", po_number="PO-1")
    current_only, _ = _repository_order(customer_reference="CUST-ONLY", po_number="PO-ONLY")
    different_customer, _ = _repository_order(customer_reference="CUST-2", po_number="PO-1")
    different_po, _ = _repository_order(customer_reference="CUST-1", po_number="PO-2")
    case_difference, _ = _repository_order(customer_reference="cust-1", po_number="po-1")
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            for order in (
                current,
                matching,
                current_only,
                different_customer,
                different_po,
                case_difference,
            ):
                await insert_order_graph(session, order, datetime(2030, 1, 3, tzinfo=UTC))
            await session.commit()

            assert await has_customer_po_duplicate(
                session, "CUST-1", "PO-1", exclude_order_id=current.id
            )
            assert not await has_customer_po_duplicate(
                session, "CUST-ONLY", "PO-ONLY", exclude_order_id=current_only.id
            )
            assert not await has_customer_po_duplicate(
                session, "CUST-3", "PO-1", exclude_order_id=current.id
            )
            assert not await has_customer_po_duplicate(
                session, "CUST-1", "PO-3", exclude_order_id=current.id
            )
            assert not await has_customer_po_duplicate(
                session, "CUST-1", "po-1", exclude_order_id=current.id
            )
            assert await has_customer_po_duplicate(
                session, "cust-1", "po-1", exclude_order_id=current.id
            )
    finally:
        await engine.dispose()


async def _assert_processed_sha_repository() -> None:
    current, current_source = _repository_order(source_hashes=("a" * 64, "b" * 64))
    current_only, current_only_source = _repository_order(source_hashes=("c" * 64,))
    other_order, other_source = _repository_order(source_hashes=("a" * 64,))
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            for order in (current, current_only, other_order):
                await insert_order_graph(session, order, datetime(2030, 1, 4, tzinfo=UTC))
            await session.commit()
            for snapshot in (
                _repository_snapshot(current.id, current_source.id, "a" * 64),
                _repository_snapshot(current_only.id, current_only_source.id, "c" * 64),
                _repository_snapshot(other_order.id, other_source.id, "a" * 64),
            ):
                await insert_extraction_snapshot(session, snapshot)
            await session.commit()

            assert not await has_processed_source_sha(
                session,
                "c" * 64,
                exclude_order_id=current_only.id,
                exclude_source_document_id=current_only_source.id,
            )
            assert await has_processed_source_sha(
                session,
                "a" * 64,
                exclude_order_id=current.id,
                exclude_source_document_id=current_source.id,
            )
            assert not await has_processed_source_sha(
                session,
                "b" * 64,
                exclude_order_id=current.id,
                exclude_source_document_id=current_source.id,
            )
    finally:
        await engine.dispose()


async def _assert_build_validation_facts() -> None:
    current, current_source = _repository_order(customer_reference="CUST-1", po_number="PO-1")
    other, other_source = _repository_order(customer_reference="CUST-1", po_number="PO-1")
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            for order in (current, other):
                await insert_order_graph(session, order, datetime(2030, 1, 5, tzinfo=UTC))
            await session.commit()
            await insert_extraction_snapshot(
                session,
                _repository_snapshot(other.id, other_source.id, "a" * 64),
            )
            await session.commit()

            facts = await build_validation_facts(
                session,
                order_id=current.id,
                source_document_id=current_source.id,
                canonical_customer_reference="CUST-1",
                po_number="PO-1",
                source_sha256="a" * 64,
            )
            assert facts.duplicate_customer_po is True
            assert facts.document_already_processed is True
            assert isinstance(facts, ValidationFacts)
            assert not hasattr(facts, "__dict__")
            with pytest.raises(FrozenInstanceError):
                facts.duplicate_customer_po = False  # type: ignore[misc]

            no_customer = await build_validation_facts(
                session,
                order_id=current.id,
                source_document_id=current_source.id,
                canonical_customer_reference=None,
                po_number="PO-1",
                source_sha256="a" * 64,
            )
            no_po = await build_validation_facts(
                session,
                order_id=current.id,
                source_document_id=current_source.id,
                canonical_customer_reference="CUST-1",
                po_number=None,
                source_sha256="a" * 64,
            )
            assert no_customer.duplicate_customer_po is False
            assert no_customer.document_already_processed is True
            assert no_po.duplicate_customer_po is False
            assert no_po.document_already_processed is True
    finally:
        await engine.dispose()


async def _assert_validation_issue_replacement() -> None:
    order, _ = _repository_order()
    first = ValidationIssue(
        rule_code="FIRST",
        severity=ValidationSeverity.ERROR,
        field="po_number",
        expected="present",
        actual=None,
        explanation="first",
    )
    second = ValidationIssue(
        rule_code="SECOND",
        severity=ValidationSeverity.WARNING,
        field="currency",
        expected="USD",
        actual="EUR",
        explanation="second",
    )
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, datetime(2030, 1, 6, tzinfo=UTC))
            await session.commit()
            await replace_validation_issues(session, order.id, (second, first))
            assert session.in_transaction()
            await session.commit()

            rows = (
                await session.scalars(
                    select(ValidationIssueModel)
                    .where(ValidationIssueModel.order_id == order.id)
                    .order_by(ValidationIssueModel.position.asc())
                )
            ).all()
            assert [row.position for row in rows] == [0, 1]
            assert [row.rule_code for row in rows] == ["SECOND", "FIRST"]
            persisted = await get_order(session, order.id)
            assert persisted is not None
            assert persisted.validation_issues == (second, first)

            await replace_validation_issues(session, order.id, ())
            await session.commit()
            assert (
                await session.scalar(
                    select(ValidationIssueModel).where(ValidationIssueModel.order_id == order.id)
                )
                is None
            )
    finally:
        await engine.dispose()


async def _assert_locked_order_read() -> None:
    order, _ = _repository_order()
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as setup_session:
            await insert_order_graph(setup_session, order, datetime(2030, 1, 7, tzinfo=UTC))
            await setup_session.commit()

        async with AsyncSession(engine) as locked_session, AsyncSession(engine) as writer_session:
            await locked_session.begin()
            locked = await get_order_for_update(locked_session, order.id)
            assert locked is not None
            assert locked.order == order

            await writer_session.begin()
            update_task = asyncio.create_task(
                writer_session.execute(
                    update(OrderModel).where(OrderModel.id == order.id).values(po_number="blocked")
                )
            )
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(update_task), timeout=0.1)
            await locked_session.rollback()
            await update_task
            await writer_session.rollback()

            normal = await get_order(locked_session, order.id)
            assert normal is not None
            assert normal.order == order
    finally:
        await engine.dispose()


async def _assert_order_snapshot_and_graph_replacement() -> None:
    order, source_document = _repository_order()
    replacement_lines = (
        OrderLine(
            id=uuid4(),
            sku="NEW-1",
            description="new one",
            quantity=Decimal("2"),
            submitted_price=Decimal("3"),
            trusted_catalogue_price=Decimal("4"),
        ),
        OrderLine(
            id=uuid4(),
            sku="NEW-2",
            description="new two",
            quantity=Decimal("5"),
            submitted_price=Decimal("6"),
            trusted_catalogue_price=Decimal("7"),
        ),
    )
    replacement_state = order.transition_to(OrderState.PROCESSING)
    replacement = Order(
        id=replacement_state.id,
        customer_reference="UPDATED-CUSTOMER",
        po_number="UPDATED-PO",
        currency="EUR",
        lines=replacement_lines,
        source_documents=replacement_state.source_documents,
        state=replacement_state.state,
    )
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, datetime(2030, 1, 8, tzinfo=UTC))
            await session.commit()
            await update_order_snapshot(session, replacement)
            await replace_order_graph(session, replacement)
            await session.commit()

            persisted = await get_order(session, order.id)
            assert persisted is not None
            assert persisted.order.customer_reference == "UPDATED-CUSTOMER"
            assert persisted.order.po_number == "UPDATED-PO"
            assert persisted.order.currency == "EUR"
            assert persisted.order.state is replacement.state
            assert persisted.order.lines == replacement_lines
            assert persisted.order.source_documents == (source_document,)
    finally:
        await engine.dispose()


async def _assert_repository_rollback() -> None:
    order, source_document = _repository_order()
    snapshot = _repository_snapshot(order.id, source_document.id, "a" * 64)
    issue = ValidationIssue(
        rule_code="ROLLBACK",
        severity=ValidationSeverity.ERROR,
        field="po_number",
        expected="present",
        actual=None,
        explanation="rollback",
    )
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            await insert_order_graph(session, order, datetime(2030, 1, 9, tzinfo=UTC))
            await session.commit()
            await insert_extraction_snapshot(session, snapshot)
            await replace_validation_issues(session, order.id, (issue,))
            await update_order_snapshot(session, order.transition_to(OrderState.PROCESSING))
            assert session.in_transaction()
            await session.rollback()

        async with AsyncSession(engine) as session:
            assert await get_extraction_snapshot(session, order.id, source_document.id) is None
            persisted = await get_order(session, order.id)
            assert persisted is not None
            assert persisted.validation_issues == ()
            assert persisted.order.state is order.state
    finally:
        await engine.dispose()


def _repository_order(
    *,
    customer_reference: str = "CUST-1",
    po_number: str = "PO-1",
    source_hashes: tuple[str, ...] = ("a" * 64,),
) -> tuple[Order, SourceDocument]:
    source_documents = tuple(
        SourceDocument(
            id=uuid4(),
            document_type=SourceDocumentType.PDF,
            name=f"fixture-{index}.pdf",
            mime_type="application/pdf",
            sha256=source_sha256,
            message_id=None,
            storage_reference=f"storage/{index}",
            metadata=(("source", "test"),),
        )
        for index, source_sha256 in enumerate(source_hashes)
    )
    order = Order.received(
        id=uuid4(),
        customer_reference=customer_reference,
        po_number=po_number,
        currency="USD",
        lines=(
            OrderLine(
                id=uuid4(),
                sku="SKU-1",
                description="fixture",
                quantity=Decimal("1"),
                submitted_price=Decimal("2"),
                trusted_catalogue_price=Decimal("3"),
            ),
        ),
        source_documents=source_documents,
    )
    return order, source_documents[0]


def _repository_snapshot(
    order_id: object,
    source_document_id: object,
    source_sha256: str,
) -> PersistedExtractionSnapshot:
    draft = ExtractionDraft(
        source_sha256=source_sha256,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Customer",
        customer_reference="CUST-1",
        po_number="PO-1",
        order_date=None,
        requested_delivery_date=None,
        currency="USD",
        lines=(
            ExtractedLine(
                sku="SKU-1",
                description="fixture",
                quantity=Decimal("1"),
                submitted_price=Decimal("2"),
            ),
        ),
        notes=None,
        evidence=(),
    )
    return PersistedExtractionSnapshot(
        id=uuid4(),
        order_id=order_id,  # type: ignore[arg-type]
        source_document_id=source_document_id,  # type: ignore[arg-type]
        source_sha256=source_sha256,
        source_document_type=SourceDocumentType.PDF,
        draft=draft,
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )


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
