"""Add bounded Phase 7 intake ownership and fencing."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_phase7_intake_ownership"
down_revision: str | None = "0006_phase9_order_syncs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable ownership metadata without activating historical orders."""

    op.add_column(
        "orders",
        sa.Column("intake_claim_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("intake_claim_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_orders_intake_claim_pair",
        "orders",
        "(intake_claim_token IS NULL AND intake_claim_expires_at IS NULL) OR "
        "(intake_claim_token IS NOT NULL AND intake_claim_expires_at IS NOT NULL)",
    )


def downgrade() -> None:
    """Remove the focused Phase 7 ownership metadata."""

    op.drop_constraint("ck_orders_intake_claim_pair", "orders", type_="check")
    op.drop_column("orders", "intake_claim_expires_at")
    op.drop_column("orders", "intake_claim_token")
