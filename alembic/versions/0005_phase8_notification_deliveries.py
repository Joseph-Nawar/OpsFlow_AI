"""Add durable Phase 8 notification delivery state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_phase8_notification_deliveries"
down_revision: str | None = "0004_phase6_review_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the single narrow notification-intent and delivery table."""

    # Alembic creates version_num as VARCHAR(32), shorter than this required ID.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_table(
        "notification_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_audit_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("provider_reference", sa.String(length=256), nullable=True),
        sa.Column("last_failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_notification_deliveries_order", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trigger_audit_event_id"],
            ["audit_events.id"],
            name="fk_notification_deliveries_trigger_event",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_deliveries"),
        sa.UniqueConstraint(
            "trigger_audit_event_id",
            "channel",
            "kind",
            name="uq_notification_deliveries_trigger_channel_kind",
        ),
        sa.CheckConstraint(
            "channel IN ('SLACK', 'GMAIL')",
            name="ck_notification_deliveries_channel",
        ),
        sa.CheckConstraint(
            "kind IN ('REVIEW_REQUIRED', 'APPROVAL_READY', 'PROCESSING_FAILED', 'ORDER_APPROVED')",
            name="ck_notification_deliveries_kind",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CLAIMED', 'DELIVERED', 'FAILED_FINAL')",
            name="ck_notification_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 3",
            name="ck_notification_deliveries_attempt_count",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_notification_deliveries_payload_object",
        ),
        sa.CheckConstraint(
            "((status = 'CLAIMED' AND claim_token IS NOT NULL "
            "AND claim_expires_at IS NOT NULL) OR "
            "(status <> 'CLAIMED' AND claim_token IS NULL "
            "AND claim_expires_at IS NULL))",
            name="ck_notification_deliveries_claim_pair",
        ),
        sa.CheckConstraint(
            "provider_reference IS NULL OR length(provider_reference) <= 256",
            name="ck_notification_deliveries_provider_reference",
        ),
        sa.CheckConstraint(
            "last_failure_code IS NULL OR last_failure_code IN "
            "('RATE_LIMITED', 'AUTHENTICATION_FAILED', 'PERMISSION_DENIED', "
            "'TARGET_NOT_FOUND', 'PROVIDER_UNAVAILABLE', 'TIMEOUT', "
            "'DELIVERY_REJECTED', 'UNKNOWN_FAILURE')",
            name="ck_notification_deliveries_failure_code",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_claim_eligibility",
        "notification_deliveries",
        ["status", "next_attempt_at", "claim_expires_at"],
    )


def downgrade() -> None:
    """Drop Phase 8 delivery records without affecting order/audit data."""

    op.drop_index(
        "ix_notification_deliveries_claim_eligibility",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
