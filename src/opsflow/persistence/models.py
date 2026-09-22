"""SQLAlchemy models for the Phase 2 relational persistence contract."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base containing the current relational business tables."""


_ORDER_STATES = (
    "RECEIVED",
    "PROCESSING",
    "EXTRACTED",
    "VALIDATED",
    "NEEDS_REVIEW",
    "READY_FOR_APPROVAL",
    "APPROVED",
    "SYNCING",
    "COMPLETED",
    "REJECTED",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class OrderModel(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            f"state IN ({_sql_values(_ORDER_STATES)})",
            name="ck_orders_state",
        ),
        CheckConstraint(
            "currency IS NULL OR (currency COLLATE \"C\") ~ '^[A-Z]{3}$'",
            name="ck_orders_currency",
        ),
        CheckConstraint(
            "((state IN ('FAILED_RETRYABLE', 'FAILED_FINAL') "
            "AND failure_origin IS NOT NULL "
            "AND failure_origin IN ('PROCESSING', 'EXTRACTED', 'SYNCING')) "
            "OR (state NOT IN ('FAILED_RETRYABLE', 'FAILED_FINAL') "
            "AND failure_origin IS NULL))",
            name="ck_orders_failure_origin",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    customer_reference: Mapped[str | None] = mapped_column(Text)
    po_number: Mapped[str | None] = mapped_column(Text)
    order_date: Mapped[date | None] = mapped_column(Date)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    failure_origin: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrderLineModel(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        UniqueConstraint("order_id", "position", name="uq_order_lines_order_position"),
        CheckConstraint("position >= 0", name="ck_order_lines_position"),
        CheckConstraint("quantity > 0", name="ck_order_lines_quantity"),
        CheckConstraint("submitted_price >= 0", name="ck_order_lines_submitted_price"),
        CheckConstraint(
            "trusted_catalogue_price >= 0",
            name="ck_order_lines_trusted_catalogue_price",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    submitted_price: Mapped[Decimal | None] = mapped_column(Numeric)
    trusted_catalogue_price: Mapped[Decimal | None] = mapped_column(Numeric)


class SourceDocumentModel(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("id", "order_id", name="uq_source_documents_id_order_id"),
        UniqueConstraint("order_id", "position", name="uq_source_documents_order_position"),
        CheckConstraint("position >= 0", name="ck_source_documents_position"),
        CheckConstraint(
            "document_type IN ('EMAIL_BODY', 'PDF', 'XLSX', 'CSV', 'FORM')",
            name="ck_source_documents_document_type",
        ),
        CheckConstraint(
            "(sha256 COLLATE \"C\") ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_source_documents_sha256",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'array'",
            name="ck_source_documents_metadata_array",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[str | None] = mapped_column(Text)
    storage_reference: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[list[list[str]]] = mapped_column("metadata", JSONB, nullable=False)


class ValidationIssueModel(Base):
    __tablename__ = "validation_issues"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_validation_issues_position"),
        CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR')",
            name="ck_validation_issues_severity",
        ),
    )

    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str | None] = mapped_column(Text)
    expected: Mapped[Any | None] = mapped_column(JSONB)
    actual: Mapped[Any | None] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_order_occurred_at_id", "order_id", "occurred_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class OrderCreationIdempotencyModel(Base):
    __tablename__ = "order_creation_idempotency"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_order_creation_idempotency_order_id"),
        CheckConstraint(
            "length(btrim(idempotency_key)) > 0 AND length(idempotency_key) <= 128",
            name="ck_order_creation_idempotency_key",
        ),
        CheckConstraint(
            "(request_fingerprint COLLATE \"C\") ~ '^[0-9a-f]{64}$'",
            name="ck_order_creation_idempotency_fingerprint",
        ),
    )

    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExtractionSnapshotModel(Base):
    """Immutable, application-owned untrusted extraction snapshot envelope."""

    __tablename__ = "extraction_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "source_document_id",
            name="uq_extraction_snapshots_order_source",
        ),
        UniqueConstraint(
            "id",
            "order_id",
            name="uq_extraction_snapshots_id_order_id",
        ),
        ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["source_document_id", "order_id"],
            ["source_documents.id", "source_documents.order_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(source_sha256 COLLATE \"C\") ~ '^[0-9a-f]{64}$'",
            name="ck_extraction_snapshots_sha256",
        ),
        CheckConstraint(
            "source_document_type IN ('EMAIL_BODY', 'PDF', 'XLSX', 'CSV', 'FORM')",
            name="ck_extraction_snapshots_document_type",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_extraction_snapshots_payload_object",
        ),
        Index("ix_extraction_snapshots_source_sha256", "source_sha256"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    order_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRevisionModel(Base):
    """Append-only canonical human-review draft revision."""

    __tablename__ = "review_revisions"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "revision_number",
            name="uq_review_revisions_order_revision",
        ),
        ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_review_revisions_order", ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["extraction_snapshot_id", "order_id"],
            ["extraction_snapshots.id", "extraction_snapshots.order_id"],
            name="fk_review_revisions_snapshot_order",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_review_revisions_revision_positive",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_review_revisions_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(changes) = 'array'",
            name="ck_review_revisions_changes_array",
        ),
        CheckConstraint(
            "length(btrim(actor)) > 0 AND length(actor) <= 128",
            name="ck_review_revisions_actor",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    order_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    extraction_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
