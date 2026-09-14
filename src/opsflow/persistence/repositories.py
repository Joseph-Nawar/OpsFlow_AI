"""Concrete persistence operations for Phase 2 durable reads."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import AuditEvent, Order, OrderState, ValidationIssue

from .mappers import (
    audit_event_from_model,
    audit_event_to_model,
    line_to_model,
    order_from_models,
    order_to_model,
    source_document_to_model,
    validation_issue_from_model,
)
from .models import (
    AuditEventModel,
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
