"""runtime role privileges for append-only and expiring tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

RUNTIME_ROLE = "asset_app"
# Append-only tables: the runtime role may INSERT and SELECT but never UPDATE or DELETE.
APPEND_ONLY = ("audit_logs", "analytics_events", "health_score_history", "work_order_status_history")


def _role_exists() -> bool:
    bind = op.get_bind()
    return bool(
        bind.exec_driver_sql(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (RUNTIME_ROLE,)
        ).scalar()
    )


def upgrade() -> None:
    if not _role_exists():  # e.g. a throw-away database without the provisioned roles
        return
    for table in APPEND_ONLY:
        op.execute(f"REVOKE UPDATE ON {table} FROM {RUNTIME_ROLE}")
    # Expired idempotency records are purged by the runtime role; no other table needs DELETE.
    op.execute(f"GRANT DELETE ON idempotency_records TO {RUNTIME_ROLE}")


def downgrade() -> None:
    if not _role_exists():
        return
    op.execute(f"REVOKE DELETE ON idempotency_records FROM {RUNTIME_ROLE}")
    for table in APPEND_ONLY:
        op.execute(f"GRANT UPDATE ON {table} TO {RUNTIME_ROLE}")
