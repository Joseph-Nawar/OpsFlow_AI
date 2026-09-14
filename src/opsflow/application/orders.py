"""Thin application operations for durable order reads and creation."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opsflow.domain import (
    AuditEvent,
    DomainValidationError,
    Order,
    OrderLine,
    SourceDocument,
    SourceDocumentType,
)
from opsflow.persistence.repositories import (
    OrderSummary,
    PersistedOrder,
    get_idempotency_record,
    insert_audit_event,
    insert_idempotency_record,
    insert_order_graph,
)
from opsflow.persistence.repositories import get_audit_events as repository_get_audit_events
from opsflow.persistence.repositories import get_order as repository_get_order
from opsflow.persistence.repositories import list_orders as repository_list_orders

from .errors import IdempotencyConflictError, OrderNotFoundError


@dataclass(frozen=True, slots=True)
class CreateLineInput:
    """Semantic client values for one order line."""

    sku: str | None
    description: str | None
    quantity: Decimal
    submitted_price: Decimal | None = None
    trusted_catalogue_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CreateSourceDocumentInput:
    """Semantic client values for one source-document reference."""

    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None = None
    storage_reference: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, tuple) or not all(
            isinstance(pair, tuple)
            and len(pair) == 2
            and all(isinstance(value, str) for value in pair)
            for pair in self.metadata
        ):
            raise DomainValidationError("metadata must be a tuple of string pairs")


@dataclass(frozen=True, slots=True)
class CreateOrderInput:
    """Semantic client values for order intake, without server-owned fields."""

    customer_reference: str | None = None
    po_number: str | None = None
    order_date: date | None = None
    requested_delivery_date: date | None = None
    currency: str | None = None
    lines: tuple[CreateLineInput, ...] = ()
    source_documents: tuple[CreateSourceDocumentInput, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.lines, tuple) or not all(
            isinstance(line, CreateLineInput) for line in self.lines
        ):
            raise DomainValidationError("lines must be a tuple of CreateLineInput")
        if not isinstance(self.source_documents, tuple) or not all(
            isinstance(document, CreateSourceDocumentInput) for document in self.source_documents
        ):
            raise DomainValidationError(
                "source_documents must be a tuple of CreateSourceDocumentInput"
            )


def canonical_order_request(request: CreateOrderInput) -> bytes:
    """Serialize semantic order input as deterministic compact UTF-8 JSON."""

    payload = {
        "customer_reference": request.customer_reference,
        "po_number": request.po_number,
        "order_date": _canonical_date(request.order_date, "order_date"),
        "requested_delivery_date": _canonical_date(
            request.requested_delivery_date, "requested_delivery_date"
        ),
        "currency": request.currency,
        "lines": [
            {
                "sku": line.sku,
                "description": line.description,
                "quantity": _canonical_decimal(line.quantity, "quantity"),
                "submitted_price": _canonical_optional_decimal(
                    line.submitted_price, "submitted_price"
                ),
                "trusted_catalogue_price": _canonical_optional_decimal(
                    line.trusted_catalogue_price, "trusted_catalogue_price"
                ),
            }
            for line in request.lines
        ],
        "source_documents": [
            {
                "document_type": _canonical_document_type(document.document_type),
                "name": document.name,
                "mime_type": document.mime_type,
                "sha256": document.sha256,
                "message_id": document.message_id,
                "storage_reference": document.storage_reference,
                "metadata": [list(pair) for pair in document.metadata],
            }
            for document in request.source_documents
        ],
    }
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DomainValidationError("order request contains unsupported JSON data") from error


def fingerprint_order_request(request: CreateOrderInput) -> str:
    """Return the lowercase SHA-256 fingerprint of semantic order input."""

    return hashlib.sha256(canonical_order_request(request)).hexdigest()


def _canonical_date(value: date | None, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not date:
        raise DomainValidationError(f"{field_name} must be a date or None")
    return value.isoformat()


def _canonical_decimal(value: Decimal, field_name: str) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainValidationError(f"{field_name} must be a finite Decimal")
    if value.is_zero():
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _canonical_optional_decimal(value: Decimal | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _canonical_decimal(value, field_name)


def _canonical_document_type(value: SourceDocumentType) -> str:
    if not isinstance(value, SourceDocumentType):
        raise DomainValidationError("document_type must be a SourceDocumentType")
    return value.value


async def create_order(
    session: AsyncSession,
    request: CreateOrderInput,
    idempotency_key: str,
    now: datetime | None = None,
) -> PersistedOrder:
    """Create or replay one atomically persisted RECEIVED order."""

    fingerprint = fingerprint_order_request(request)
    order = _order_from_create_input(request)
    effective_now = _effective_utc_now(now)
    audit_event = AuditEvent(
        id=uuid4(),
        order_id=order.id,
        event_type="ORDER_RECEIVED",
        actor="system",
        occurred_at=effective_now,
        description="Order received through API intake.",
    )

    try:
        async with session.begin():
            await insert_order_graph(session, order, effective_now)
            await insert_audit_event(session, audit_event)
            await insert_idempotency_record(
                session,
                idempotency_key,
                fingerprint,
                order.id,
                effective_now,
            )
    except IntegrityError as error:
        if not _is_idempotency_key_conflict(error):
            raise
        return await _resolve_idempotency_race(session, idempotency_key, fingerprint)

    return PersistedOrder(order=order, created_at=effective_now, validation_issues=())


def _order_from_create_input(request: CreateOrderInput) -> Order:
    lines = tuple(
        OrderLine(
            id=uuid4(),
            sku=line.sku,
            description=line.description,
            quantity=line.quantity,
            submitted_price=line.submitted_price,
            trusted_catalogue_price=line.trusted_catalogue_price,
        )
        for line in request.lines
    )
    source_documents = tuple(
        SourceDocument(
            id=uuid4(),
            document_type=document.document_type,
            name=document.name,
            mime_type=document.mime_type,
            sha256=document.sha256,
            message_id=document.message_id,
            storage_reference=document.storage_reference,
            metadata=document.metadata,
        )
        for document in request.source_documents
    )
    return Order.received(
        id=uuid4(),
        customer_reference=request.customer_reference,
        po_number=request.po_number,
        order_date=request.order_date,
        requested_delivery_date=request.requested_delivery_date,
        currency=request.currency,
        lines=lines,
        source_documents=source_documents,
    )


def _effective_utc_now(now: datetime | None) -> datetime:
    value = datetime.now(UTC) if now is None else now
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise DomainValidationError("now must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _is_idempotency_key_conflict(error: BaseException) -> bool:
    return getattr(getattr(error, "orig", None), "constraint_name", None) == (
        "order_creation_idempotency_pkey"
    )


async def _resolve_idempotency_race(
    session: AsyncSession, idempotency_key: str, fingerprint: str
) -> PersistedOrder:
    try:
        record = await get_idempotency_record(session, idempotency_key)
        if record is None:
            raise RuntimeError("idempotency conflict has no committed record")
        if record.request_fingerprint != fingerprint:
            raise IdempotencyConflictError(idempotency_key)
        result = await repository_get_order(session, record.order_id)
        if result is None:
            raise RuntimeError("idempotency record references a missing order")
        return result
    finally:
        await session.rollback()


async def get_order(session: AsyncSession, order_id: UUID) -> PersistedOrder:
    """Return one persisted order or raise when it is missing."""

    result = await repository_get_order(session, order_id)
    if result is None:
        raise OrderNotFoundError(order_id)
    return result


async def list_orders(
    session: AsyncSession, limit: int, offset: int
) -> tuple[tuple[OrderSummary, ...], int]:
    """Pass through deterministic repository summaries and total count."""

    return await repository_list_orders(session, limit, offset)


async def get_order_audit(session: AsyncSession, order_id: UUID) -> tuple[AuditEvent, ...]:
    """Return audit events for an existing order, including an empty history."""

    if await repository_get_order(session, order_id) is None:
        raise OrderNotFoundError(order_id)
    return await repository_get_audit_events(session, order_id)
