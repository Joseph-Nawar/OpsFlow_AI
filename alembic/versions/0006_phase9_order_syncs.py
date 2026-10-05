"""Add durable Phase 9 order synchronization state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_phase9_order_syncs"
down_revision: str | None = "0005_phase8_notification_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STEPS = (
    "ODOO_LOOKUP",
    "ODOO_BRIDGE",
    "HUBSPOT_COMPANY",
    "HUBSPOT_DEAL",
    "HUBSPOT_ASSOCIATION",
)
_FAILURE_CODES = (
    "INTEGRATION_CONFIG",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_RATE_LIMIT",
    "PROVIDER_INVALID_RESPONSE",
    "PROVIDER_PENDING",
    "PROVIDER_REJECTED",
    "TRUSTED_CUSTOMER_MISSING",
    "TRUSTED_CUSTOMER_AMBIGUOUS",
    "TRUSTED_PRODUCT_MISSING",
    "TRUSTED_PRODUCT_CHANGED",
    "INVENTORY_INSUFFICIENT",
    "WORKER_LEASE_EXHAUSTED",
    "IDEMPOTENCY_CONFLICT",
    "RECONCILIATION_REQUIRED",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Create the single durable synchronization row per OpsFlow order."""

    op.create_table(
        "order_syncs",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("retry_generation", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("odoo_sale_order_id", sa.BigInteger(), nullable=True),
        sa.Column("odoo_sale_order_name", sa.Text(), nullable=True),
        sa.Column("hubspot_company_id", sa.Text(), nullable=True),
        sa.Column("hubspot_deal_id", sa.Text(), nullable=True),
        sa.Column("hubspot_association_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_flight_step", sa.Text(), nullable=True),
        sa.Column("last_failure_step", sa.Text(), nullable=True),
        sa.Column("last_failure_code", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
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
            ["order_id"], ["orders.id"], name="fk_order_syncs_order", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("order_id", name="pk_order_syncs"),
        sa.CheckConstraint(
            "(claim_token IS NULL AND claim_expires_at IS NULL) OR "
            "(claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name="ck_order_syncs_claim_pair",
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 3", name="ck_order_syncs_attempt_count"),
        sa.CheckConstraint("retry_generation >= 0", name="ck_order_syncs_retry_generation"),
        sa.CheckConstraint(
            f"in_flight_step IS NULL OR in_flight_step IN ({_sql_values(_STEPS)})",
            name="ck_order_syncs_in_flight_step",
        ),
        sa.CheckConstraint(
            f"last_failure_step IS NULL OR last_failure_step IN ({_sql_values(_STEPS)})",
            name="ck_order_syncs_failure_step",
        ),
        sa.CheckConstraint(
            f"last_failure_code IS NULL OR last_failure_code IN ({_sql_values(_FAILURE_CODES)})",
            name="ck_order_syncs_failure_code",
        ),
        sa.CheckConstraint(
            "(last_failure_step IS NULL AND last_failure_code IS NULL) OR "
            "(last_failure_step IS NOT NULL AND last_failure_code IS NOT NULL)",
            name="ck_order_syncs_failure_pair",
        ),
        sa.CheckConstraint(
            "(odoo_sale_order_id IS NULL AND odoo_sale_order_name IS NULL) OR "
            "(odoo_sale_order_id IS NOT NULL AND odoo_sale_order_name IS NOT NULL AND "
            "odoo_sale_order_id > 0 AND "
            "length(btrim(odoo_sale_order_name)) BETWEEN 1 AND 256)",
            name="ck_order_syncs_odoo_receipt_pair",
        ),
        sa.CheckConstraint(
            "hubspot_company_id IS NULL OR length(btrim(hubspot_company_id)) BETWEEN 1 AND 256",
            name="ck_order_syncs_hubspot_company_id",
        ),
        sa.CheckConstraint(
            "hubspot_deal_id IS NULL OR length(btrim(hubspot_deal_id)) BETWEEN 1 AND 256",
            name="ck_order_syncs_hubspot_deal_id",
        ),
        sa.CheckConstraint(
            "hubspot_association_confirmed_at IS NULL OR "
            "(hubspot_company_id IS NOT NULL AND hubspot_deal_id IS NOT NULL)",
            name="ck_order_syncs_association_receipt",
        ),
    )
    op.create_index(
        "uq_order_syncs_odoo_sale_order_id",
        "order_syncs",
        ["odoo_sale_order_id"],
        unique=True,
        postgresql_where=sa.text("odoo_sale_order_id IS NOT NULL"),
    )
    op.create_index(
        "uq_order_syncs_hubspot_deal_id",
        "order_syncs",
        ["hubspot_deal_id"],
        unique=True,
        postgresql_where=sa.text("hubspot_deal_id IS NOT NULL"),
    )
    op.create_index(
        "ix_order_syncs_claim_eligibility",
        "order_syncs",
        ["next_attempt_at", "claim_expires_at"],
    )


def downgrade() -> None:
    """Drop the M9B table; this removes its sync receipts and is test-only after use."""

    op.drop_index("ix_order_syncs_claim_eligibility", table_name="order_syncs")
    op.drop_index("uq_order_syncs_hubspot_deal_id", table_name="order_syncs")
    op.drop_index("uq_order_syncs_odoo_sale_order_id", table_name="order_syncs")
    op.drop_table("order_syncs")
