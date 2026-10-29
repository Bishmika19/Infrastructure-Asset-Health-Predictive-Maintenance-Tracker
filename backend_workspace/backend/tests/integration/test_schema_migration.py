"""Verify the migrated schema and role privileges on the workspace PostgreSQL instance."""

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings

EXPECTED_TABLES = {
    "alerts",
    "analytics_events",
    "assets",
    "audit_logs",
    "health_score_history",
    "idempotency_records",
    "inspection_photos",
    "inspections",
    "outbox_events",
    "scheduled_runs",
    "users",
    "work_order_status_history",
    "work_orders",
}
APPEND_ONLY = ("audit_logs", "analytics_events", "health_score_history", "work_order_status_history")


@pytest.fixture(scope="module")
def engines():
    """Yield (migration, runtime) engines or skip when the database is not reachable."""
    settings = get_settings()
    if not (settings.database_url and settings.migration_database_url):
        pytest.skip("database URLs are not configured")
    migration = create_engine(settings.migration_database_url)
    runtime = create_engine(settings.database_url)
    try:
        with migration.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("workspace database is not reachable")
    yield migration, runtime
    migration.dispose()
    runtime.dispose()


def test_all_13_tables_exist_at_head(engines):
    migration, _ = engines
    with migration.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert EXPECTED_TABLES <= tables
    assert version == "0002"


def test_runtime_role_cannot_update_or_delete_append_only_tables(engines):
    _, runtime = engines
    with runtime.connect() as conn:
        grants = {
            (row[0], row[1])
            for row in conn.execute(
                text(
                    "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = 'asset_app'"
                )
            )
        }
    for table in APPEND_ONLY:
        assert (table, "INSERT") in grants
        assert (table, "UPDATE") not in grants
        assert (table, "DELETE") not in grants


def test_runtime_role_cannot_create_objects(engines):
    _, runtime = engines
    with runtime.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text("CREATE TABLE should_not_exist (id int)"))
