"""Concrete persistence operations for Phase 2 durable reads."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import AuditEvent, Order, OrderState, ValidationIssue
from opsflow.validation import ValidationFacts

from .mappers import (
    PersistedExtractionSnapshot,
    audit_event_from_model,
    audit_event_to_model,
    extraction_snapshot_from_model,
    extraction_snapshot_to_model,
    line_to_model,
    order_from_models,
    order_to_model,
    source_document_to_model,
    validation_issue_from_model,
)
from .models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    SourceDocumentModel,
    ValidationIssueModel,
)


@dataclass(frozen=True, slots=True)
class PersistedOrder:
    """A complete validated order plus persistence-only read data."""

    order: Order
    created_at: datetime
    validation_issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class OrderSummary:
    """The approved summary fields returned by order listing."""

    id: UUID
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    state: OrderState
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Typed persistence data for one order-creation key."""

    idempotency_key: str
    request_fingerprint: str
    order_id: UUID
    created_at: datetime


_CANONICAL_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


async def insert_extraction_snapshot(
    session: AsyncSession,
    snapshot: PersistedExtractionSnapshot,
) -> None:
    """Insert one immutable extraction snapshot without committing."""

    session.add(extraction_snapshot_to_model(snapshot))
    await session.flush()


async def get_extraction_snapshot(
    session: AsyncSession,
    order_id: UUID,
    source_document_id: UUID,
) -> PersistedExtractionSnapshot | None:
    """Return the snapshot for one exact order/source pair, if present."""

    row = await session.scalar(
        select(ExtractionSnapshotModel).where(
            ExtractionSnapshotModel.order_id == order_id,
            ExtractionSnapshotModel.source_document_id == source_document_id,
        )
    )
    if row is None:
        return None
    return extraction_snapshot_from_model(row)


async def has_customer_po_duplicate(
    session: AsyncSession,
    customer_reference: str,
    po_number: str,
    *,
    exclude_order_id: UUID,
) -> bool:
    """Check an exact customer-reference/PO pair outside one current order."""

    match = await session.scalar(
        select(OrderModel.id)
        .where(
            OrderModel.customer_reference == customer_reference,
            OrderModel.po_number == po_number,
            OrderModel.id != exclude_order_id,
        )
        .limit(1)
    )
    return match is not None


async def has_processed_source_sha(
    session: AsyncSession,
    source_sha256: str,
    *,
    exclude_order_id: UUID,
    exclude_source_document_id: UUID,
) -> bool:
    """Check a canonical source SHA outside one exact order/source pair."""

    if type(source_sha256) is not str or _CANONICAL_SHA256.fullmatch(source_sha256) is None:
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    match = await session.scalar(
        select(ExtractionSnapshotModel.id)
        .where(
            ExtractionSnapshotModel.source_sha256 == source_sha256,
            ~(
                (ExtractionSnapshotModel.order_id == exclude_order_id)
                & (ExtractionSnapshotModel.source_document_id == exclude_source_document_id)
            ),
        )
        .limit(1)
    )
    return match is not None


async def get_source_document_order_id(
    session: AsyncSession,
    source_document_id: UUID,
) -> UUID | None:
    """Return the owning order ID for one source document, if it exists."""

    owner_id: UUID | None = await session.scalar(
        select(SourceDocumentModel.order_id).where(SourceDocumentModel.id == source_document_id)
    )
    return owner_id


async def build_validation_facts(
    session: AsyncSession,
    *,
    order_id: UUID,
    source_document_id: UUID,
    canonical_customer_reference: str | None,
    po_number: str | None,
    source_sha256: str,
) -> ValidationFacts:
    """Build immutable local facts from focused OpsFlow persistence queries."""

    duplicate_customer_po = False
    if canonical_customer_reference is not None and po_number is not None:
        duplicate_customer_po = await has_customer_po_duplicate(
            session,
            canonical_customer_reference,
            po_number,
            exclude_order_id=order_id,
        )
    document_already_processed = await has_processed_source_sha(
        session,
        source_sha256,
        exclude_order_id=order_id,
        exclude_source_document_id=source_document_id,
    )
    return ValidationFacts(
        duplicate_customer_po=duplicate_customer_po,
        document_already_processed=document_already_processed,
    )


async def replace_validation_issues(
    session: AsyncSession,
    order_id: UUID,
    issues: tuple[ValidationIssue, ...],
) -> None:
    """Replace one order's complete issue set in tuple order without committing."""

    await session.execute(
        delete(ValidationIssueModel).where(ValidationIssueModel.order_id == order_id)
    )
    await session.flush()
    session.add_all(
        [
            ValidationIssueModel(
                order_id=order_id,
                position=position,
                rule_code=issue.rule_code,
                severity=issue.severity.value,
                field=issue.field,
                expected=issue.expected,
                actual=issue.actual,
                explanation=issue.explanation,
            )
            for position, issue in enumerate(issues)
        ]
    )
    await session.flush()


async def insert_order_graph(session: AsyncSession, order: Order, created_at: datetime) -> None:
    """Add an order and its ordered children without committing the transaction."""

    session.add(order_to_model(order, created_at))
    await session.flush()
    session.add_all(
        [line_to_model(order.id, position, line) for position, line in enumerate(order.lines)]
        + [
            source_document_to_model(order.id, position, document)
            for position, document in enumerate(order.source_documents)
        ]
    )
    await session.flush()


async def get_order(session: AsyncSession, order_id: UUID) -> PersistedOrder | None:
    """Load and reconstruct one complete order graph, if it exists."""

    return await _load_order(session, order_id, for_update=False)


async def get_order_for_update(
    session: AsyncSession,
    order_id: UUID,
) -> PersistedOrder | None:
    """Lock and reconstruct one complete order graph for a caller transaction."""

    return await _load_order(session, order_id, for_update=True)


async def _load_order(
    session: AsyncSession,
    order_id: UUID,
    *,
    for_update: bool,
) -> PersistedOrder | None:
    if for_update:
        order_row = await session.scalar(
            select(OrderModel).where(OrderModel.id == order_id).with_for_update()
        )
    else:
        order_row = await session.get(OrderModel, order_id)
    if order_row is None:
        return None

    line_rows = (
        await session.scalars(
            select(OrderLineModel)
            .where(OrderLineModel.order_id == order_id)
            .order_by(OrderLineModel.position.asc())
        )
    ).all()
    document_rows = (
        await session.scalars(
            select(SourceDocumentModel)
            .where(SourceDocumentModel.order_id == order_id)
            .order_by(SourceDocumentModel.position.asc())
        )
    ).all()
    issue_rows = (
        await session.scalars(
            select(ValidationIssueModel)
            .where(ValidationIssueModel.order_id == order_id)
            .order_by(ValidationIssueModel.position.asc())
        )
    ).all()

    return PersistedOrder(
        order=order_from_models(order_row, line_rows, document_rows),
        created_at=order_row.created_at,
        validation_issues=tuple(validation_issue_from_model(row) for row in issue_rows),
    )


async def update_order_snapshot(session: AsyncSession, order: Order) -> None:
    """Persist one supplied order scalar/state snapshot without committing."""

    row = await session.get(OrderModel, order.id)
    if row is None:
        raise ValueError("cannot update a missing order")
    row.customer_reference = order.customer_reference
    row.po_number = order.po_number
    row.order_date = order.order_date
    row.requested_delivery_date = order.requested_delivery_date
    row.currency = order.currency
    row.state = order.state.value
    row.failure_origin = order.failure_origin.value if order.failure_origin else None
    await session.flush()


async def replace_order_graph(session: AsyncSession, order: Order) -> None:
    """Replace trusted ordered lines while preserving source-document rows."""

    await session.execute(delete(OrderLineModel).where(OrderLineModel.order_id == order.id))
    await session.flush()
    session.add_all(
        [line_to_model(order.id, position, line) for position, line in enumerate(order.lines)]
    )
    await session.flush()


async def list_orders(
    session: AsyncSession, limit: int, offset: int
) -> tuple[tuple[OrderSummary, ...], int]:
    """Return deterministic order summaries and the unfiltered total count."""

    total = await session.scalar(select(func.count()).select_from(OrderModel))
    rows = (
        await session.scalars(
            select(OrderModel)
            .order_by(OrderModel.created_at.desc(), OrderModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    summaries = tuple(
        OrderSummary(
            id=row.id,
            customer_reference=row.customer_reference,
            po_number=row.po_number,
            order_date=row.order_date,
            requested_delivery_date=row.requested_delivery_date,
            currency=row.currency,
            state=OrderState(row.state),
            created_at=row.created_at,
        )
        for row in rows
    )
    return summaries, int(total or 0)


async def get_audit_events(session: AsyncSession, order_id: UUID) -> tuple[AuditEvent, ...]:
    """Return an order's audit records in deterministic chronological order."""

    rows = (
        await session.scalars(
            select(AuditEventModel)
            .where(AuditEventModel.order_id == order_id)
            .order_by(AuditEventModel.occurred_at.asc(), AuditEventModel.id.asc())
        )
    ).all()
    return tuple(audit_event_from_model(row) for row in rows)


async def insert_audit_event(session: AsyncSession, event: AuditEvent) -> None:
    """Add one audit event without committing the caller's transaction."""

    session.add(audit_event_to_model(event))
    await session.flush()


async def insert_idempotency_record(
    session: AsyncSession,
    idempotency_key: str,
    request_fingerprint: str,
    order_id: UUID,
    created_at: datetime,
) -> None:
    """Add one creation key and flush so its database uniqueness is decisive."""

    session.add(
        OrderCreationIdempotencyModel(
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            order_id=order_id,
            created_at=created_at,
        )
    )
    await session.flush()


async def get_idempotency_record(
    session: AsyncSession, idempotency_key: str
) -> IdempotencyRecord | None:
    """Return typed idempotency data without exposing its ORM row."""

    row = await session.get(OrderCreationIdempotencyModel, idempotency_key)
    if row is None:
        return None
    return IdempotencyRecord(
        idempotency_key=row.idempotency_key,
        request_fingerprint=row.request_fingerprint,
        order_id=row.order_id,
        created_at=row.created_at,
    )
