"""Create the Phase 2 persistence schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase2_persistence"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the six Phase 2 business tables and their constraints."""

    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("customer_reference", sa.Text(), nullable=True),
        sa.Column("po_number", sa.Text(), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("requested_delivery_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("failure_origin", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "state IN ('RECEIVED', 'PROCESSING', 'EXTRACTED', 'VALIDATED', "
            "'NEEDS_REVIEW', 'READY_FOR_APPROVAL', 'APPROVED', 'SYNCING', "
            "'COMPLETED', 'REJECTED', 'FAILED_RETRYABLE', 'FAILED_FINAL')",
            name="ck_orders_state",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR (currency COLLATE \"C\") ~ '^[A-Z]{3}$'",
            name="ck_orders_currency",
        ),
        sa.CheckConstraint(
            "((state IN ('FAILED_RETRYABLE', 'FAILED_FINAL') "
            "AND failure_origin IS NOT NULL "
            "AND failure_origin IN ('PROCESSING', 'EXTRACTED', 'SYNCING')) "
            "OR (state NOT IN ('FAILED_RETRYABLE', 'FAILED_FINAL') "
            "AND failure_origin IS NULL))",
            name="ck_orders_failure_origin",
        ),
    )

    op.create_table(
        "order_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("submitted_price", sa.Numeric(), nullable=True),
        sa.Column("trusted_catalogue_price", sa.Numeric(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("order_id", "position", name="uq_order_lines_order_position"),
        sa.CheckConstraint("position >= 0", name="ck_order_lines_position"),
        sa.CheckConstraint("quantity > 0", name="ck_order_lines_quantity"),
        sa.CheckConstraint("submitted_price >= 0", name="ck_order_lines_submitted_price"),
        sa.CheckConstraint(
            "trusted_catalogue_price >= 0",
            name="ck_order_lines_trusted_catalogue_price",
        ),
    )

    op.create_table(
        "source_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("storage_reference", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("order_id", "position", name="uq_source_documents_order_position"),
        sa.CheckConstraint("position >= 0", name="ck_source_documents_position"),
        sa.CheckConstraint(
            "document_type IN ('EMAIL_BODY', 'PDF', 'XLSX', 'CSV', 'FORM')",
            name="ck_source_documents_document_type",
        ),
        sa.CheckConstraint(
            "(sha256 COLLATE \"C\") ~ '^[0-9A-Fa-f]{64}$'",
            name="ck_source_documents_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'array'",
            name="ck_source_documents_metadata_array",
        ),
    )

    op.create_table(
        "validation_issues",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=True),
        sa.Column("expected", postgresql.JSONB(), nullable=True),
        sa.Column("actual", postgresql.JSONB(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("order_id", "position"),
        sa.CheckConstraint("position >= 0", name="ck_validation_issues_position"),
        sa.CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR')",
            name="ck_validation_issues_severity",
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_audit_events_order_occurred_at_id",
        "audit_events",
        ["order_id", "occurred_at", "id"],
    )

    op.create_table(
        "order_creation_idempotency",
        sa.Column("idempotency_key", sa.String(), primary_key=True),
        sa.Column("request_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("order_id", name="uq_order_creation_idempotency_order_id"),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0 AND length(idempotency_key) <= 128",
            name="ck_order_creation_idempotency_key",
        ),
        sa.CheckConstraint(
            "(request_fingerprint COLLATE \"C\") ~ '^[0-9a-f]{64}$'",
            name="ck_order_creation_idempotency_fingerprint",
        ),
    )


def downgrade() -> None:
    """Drop Phase 2 tables in foreign-key-safe order."""

    op.drop_table("order_creation_idempotency")
    op.drop_index("ix_audit_events_order_occurred_at_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("validation_issues")
    op.drop_table("source_documents")
    op.drop_table("order_lines")
    op.drop_table("orders")
