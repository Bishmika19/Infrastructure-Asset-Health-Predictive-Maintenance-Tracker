"""Append-only audit writer used by services inside their unit of work (AC-15)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.modules.audit.models import AuditLog
from app.shared.principal import ACTOR_USER, Actor

# Audit event names written by the identity module.
EVENT_LOGIN_SUCCEEDED = "auth.login_succeeded"
EVENT_LOGIN_FAILED = "auth.login_failed"
EVENT_LOGIN_THROTTLED = "auth.login_throttled"

# Domain events written by the asset, scoring, inspection and work-order services.
EVENT_ASSET_CREATED = "asset.created"
EVENT_ASSET_UPDATED = "asset.updated"
EVENT_ASSET_DEACTIVATED = "asset.deactivated"
EVENT_SCORE_RECALCULATED = "score.recalculated"
EVENT_ALERT_OPENED = "alert.opened"
EVENT_ALERT_RESOLVED = "alert.resolved"
EVENT_INSPECTION_LOGGED = "inspection.logged"
EVENT_WORK_ORDER_CREATED = "work_order.created"
EVENT_WORK_ORDER_UPDATED = "work_order.updated"
EVENT_HISTORY_VIEWED = "history.viewed"

_FALLBACK_REQUEST_ID = "no-request"


class AuditWriter:
    """Insert audit rows; never updates or deletes (the runtime role cannot)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # PUBLIC_INTERFACE
    def record(
        self,
        event_type: str,
        actor: Actor,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        attempted_username: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> AuditLog:
        """Append one audit row with the current request ID (or the supplied one).

        ``actor.id`` is stored only for ``user`` actors; ``system`` and ``anonymous``
        rows carry no user reference.
        """
        row = AuditLog(
            event_type=event_type,
            actor_id=actor.id if actor.kind == ACTOR_USER else None,
            actor_kind=actor.kind,
            attempted_username=attempted_username[:128] if attempted_username else None,
            entity_type=entity_type,
            entity_id=entity_id,
            event_metadata=metadata or {},
            request_id=request_id or request_id_var.get() or _FALLBACK_REQUEST_ID,
        )
        self._session.add(row)
        self._session.flush()
        return row
