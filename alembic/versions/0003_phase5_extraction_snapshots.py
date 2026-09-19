"""Create the Phase 5 immutable extraction-snapshot table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase5_extraction_snapshots"
down_revision: str | None = "0002_phase2_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the immutable extraction-snapshot persistence boundary."""

    op.create_unique_constraint(
        "uq_source_documents_id_order_id",
        "source_documents",
        ["id", "order_id"],
    )
    op.create_table(
        "extraction_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_sha256", sa.Text(), nullable=False),
        sa.Column("source_document_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "order_id",
            "source_document_id",
            name="uq_extraction_snapshots_order_source",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id", "order_id"],
            ["source_documents.id", "source_documents.order_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(source_sha256 COLLATE \"C\") ~ '^[0-9a-f]{64}$'",
            name="ck_extraction_snapshots_sha256",
        ),
        sa.CheckConstraint(
            "source_document_type IN ('EMAIL_BODY', 'PDF', 'XLSX', 'CSV', 'FORM')",
            name="ck_extraction_snapshots_document_type",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_extraction_snapshots_payload_object",
        ),
    )
    op.create_index(
        "ix_extraction_snapshots_source_sha256",
        "extraction_snapshots",
        ["source_sha256"],
    )


def downgrade() -> None:
    """Drop the snapshot table before its supporting source ownership key."""

    op.drop_index(
        "ix_extraction_snapshots_source_sha256",
        table_name="extraction_snapshots",
    )
    op.drop_table("extraction_snapshots")
    op.drop_constraint(
        "uq_source_documents_id_order_id",
        "source_documents",
        type_="unique",
    )
