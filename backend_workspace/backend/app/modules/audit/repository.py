"""Read access to ``audit_logs`` needed by other modules (login throttling)."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog


class AuditRepository:
    """Counting queries over the append-only audit log."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def count_events_since(
        self,
        event_type: str,
        since: dt.datetime,
        attempted_username: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> int:
        """Count ``event_type`` rows since ``since`` for a username and/or client IP."""
        statement = select(func.count()).select_from(AuditLog).where(
            AuditLog.event_type == event_type, AuditLog.occurred_at >= since
        )
        if attempted_username is not None:
            statement = statement.where(AuditLog.attempted_username == attempted_username)
        if client_ip is not None:
            statement = statement.where(AuditLog.event_metadata["clientIp"].astext == client_ip)
        return int(self._session.execute(statement).scalar_one())

    def oldest_event_since(
        self,
        event_type: str,
        since: dt.datetime,
        attempted_username: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> Optional[dt.datetime]:
        """Return the oldest matching event time in the window (for Retry-After)."""
        statement = select(func.min(AuditLog.occurred_at)).where(
            AuditLog.event_type == event_type, AuditLog.occurred_at >= since
        )
        if attempted_username is not None:
            statement = statement.where(AuditLog.attempted_username == attempted_username)
        if client_ip is not None:
            statement = statement.where(AuditLog.event_metadata["clientIp"].astext == client_ip)
        return self._session.execute(statement).scalar_one()
