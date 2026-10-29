"""fence outbox delivery leases

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add lease ownership and fencing required for safe outbox acknowledgement."""
    op.add_column("outbox_events", sa.Column("lease_owner", sa.Text(), nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_check_constraint(
        "ck_outbox_events_fencing_positive",
        "outbox_events",
        "fencing_token > 0",
    )


def downgrade() -> None:
    """Remove worker lease fencing on development-only migration rollback."""
    op.drop_constraint("ck_outbox_events_fencing_positive", "outbox_events", type_="check")
    op.drop_column("outbox_events", "fencing_token")
    op.drop_column("outbox_events", "lease_owner")
