"""Alembic environment: runs migrations as the migration role (asset_migrator)."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.db.registry import Base

target_metadata = Base.metadata


def _url() -> str:
    url = get_settings().migration_database_url
    if not url:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is not configured (see database_workspace/database/"
            "database_urls.env); migrations must not run as the runtime role."
        )
    return url


def run_migrations_offline() -> None:
    """Emit SQL without a live connection."""
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database."""
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
