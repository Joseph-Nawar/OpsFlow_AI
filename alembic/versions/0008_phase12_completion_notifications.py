"""Allow durable post-sync completion notification intents."""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_phase12_completion_notifications"
down_revision: str | None = "0007_phase7_intake_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend the existing notification kind allowlist without rewriting rows."""

    op.drop_constraint(
        "ck_notification_deliveries_kind",
        "notification_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_kind",
        "notification_deliveries",
        "kind IN ('REVIEW_REQUIRED', 'APPROVAL_READY', 'PROCESSING_FAILED', "
        "'ORDER_APPROVED', 'ORDER_SYNC_COMPLETED')",
    )


def downgrade() -> None:
    """Restore the prior supported notification kinds after completion rows are removed."""

    op.drop_constraint(
        "ck_notification_deliveries_kind",
        "notification_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_notification_deliveries_kind",
        "notification_deliveries",
        "kind IN ('REVIEW_REQUIRED', 'APPROVAL_READY', 'PROCESSING_FAILED', 'ORDER_APPROVED')",
    )
