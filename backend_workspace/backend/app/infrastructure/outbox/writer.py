"""Enqueue notification events in the caller's transaction (DEC-07)."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.infrastructure.outbox.models import OutboxEvent

EVENT_ASSET_FLAGGED_EMAIL = "asset_flagged_email"


class OutboxWriter:
    """Insert pending outbox rows; the worker dispatcher delivers them later."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # PUBLIC_INTERFACE
    def enqueue(
        self, event_type: str, aggregate_type: str, aggregate_id: str, payload: Dict[str, Any]
    ) -> OutboxEvent:
        """Add a pending event that commits or rolls back with the business change."""
        row = OutboxEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        self._session.add(row)
        self._session.flush()
        return row
