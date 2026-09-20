"""Create immutable Phase 6 review revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_phase6_review_revisions"
down_revision: str | None = "0003_phase5_extraction_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add immutable review history with database-enforced snapshot ownership."""

    op.create_unique_constraint(
        "uq_extraction_snapshots_id_order_id",
        "extraction_snapshots",
        ["id", "order_id"],
    )
    op.create_table(
        "review_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "order_id",
            "revision_number",
            name="uq_review_revisions_order_revision",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_review_revisions_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_snapshot_id", "order_id"],
            ["extraction_snapshots.id", "extraction_snapshots.order_id"],
            name="fk_review_revisions_snapshot_order",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_review_revisions_revision_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_review_revisions_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changes) = 'array'",
            name="ck_review_revisions_changes_array",
        ),
        sa.CheckConstraint(
            "length(btrim(actor)) > 0 AND length(actor) <= 128",
            name="ck_review_revisions_actor",
        ),
    )


def downgrade() -> None:
    """Remove review revisions before their supporting ownership key."""

    op.drop_table("review_revisions")
    op.drop_constraint(
        "uq_extraction_snapshots_id_order_id",
        "extraction_snapshots",
        type_="unique",
    )
