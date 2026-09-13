"""Create the empty OpsFlow baseline migration."""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the baseline without creating business tables."""


def downgrade() -> None:
    """Revert the empty baseline migration."""
