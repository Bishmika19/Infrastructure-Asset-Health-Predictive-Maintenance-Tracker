"""Engine and session factory with a bounded pool and finite wait (DEC-12)."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_cached_settings


# PUBLIC_INTERFACE
def build_engine(url: str, settings: Settings) -> Engine:
    """Create an engine for ``url`` using the pool limits from ``settings``."""
    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide runtime-role engine (created lazily)."""
    settings = get_cached_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return build_engine(settings.database_url, settings)


# PUBLIC_INTERFACE
def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine`` (default: runtime engine)."""
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)


# PUBLIC_INTERFACE
def database_is_usable(settings: Settings) -> bool:
    """Return True when the runtime role can run ``SELECT 1`` (used by readiness)."""
    if not settings.database_url:
        return False
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        return False
