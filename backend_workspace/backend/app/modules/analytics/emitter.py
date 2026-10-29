"""Allow-listed product analytics emitter writing ``analytics_events`` (A-20, AC-16).

Only the PRD Section 8 events with their documented properties can be emitted, so
free-form or personal data never reaches the table. Emission happens inside the
caller's transaction and therefore commits or rolls back with the business change.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Mapping

from sqlalchemy.orm import Session

from app.modules.analytics.models import AnalyticsEvent

ASSET_CREATED = "asset_created"
ASSET_UPDATED = "asset_updated"
ASSET_DEACTIVATED = "asset_deactivated"
INSPECTION_LOGGED = "inspection_logged"
HEALTH_SCORE_RECALCULATED = "health_score_recalculated"
ASSET_FLAGGED = "asset_flagged"
WORK_ORDER_CREATED = "work_order_created"
WORK_ORDER_STATUS_CHANGED = "work_order_status_changed"
ASSET_HISTORY_VIEWED = "asset_history_viewed"

# Event name -> exact property names documented in PRD Section 8.
ALLOWED_EVENTS: Dict[str, FrozenSet[str]] = {
    ASSET_CREATED: frozenset({"asset_id", "asset_type", "location"}),
    ASSET_UPDATED: frozenset({"asset_id", "changed_fields"}),
    ASSET_DEACTIVATED: frozenset({"asset_id"}),
    INSPECTION_LOGGED: frozenset({"asset_id", "condition_rating", "photo_count"}),
    HEALTH_SCORE_RECALCULATED: frozenset(
        {"asset_id", "previous_score", "new_score", "color_band", "trigger_type"}
    ),
    ASSET_FLAGGED: frozenset({"asset_id", "score_at_flag"}),
    WORK_ORDER_CREATED: frozenset({"asset_id", "work_order_id", "priority", "assignee_id"}),
    WORK_ORDER_STATUS_CHANGED: frozenset(
        {"work_order_id", "previous_status", "new_status", "actor_role"}
    ),
    ASSET_HISTORY_VIEWED: frozenset({"asset_id", "viewer_role"}),
}


class AnalyticsEmitter:
    """Insert allow-listed analytics events in the caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # PUBLIC_INTERFACE
    def emit(self, event_name: str, properties: Mapping[str, Any]) -> AnalyticsEvent:
        """Record ``event_name`` with exactly its documented properties.

        Raises:
            ValueError: the event is not allow-listed or the properties differ from the
                documented set (a programming error, never caused by client input).
        """
        allowed = ALLOWED_EVENTS.get(event_name)
        if allowed is None:
            raise ValueError(f"analytics event not allow-listed: {event_name}")
        if set(properties) != allowed:
            raise ValueError(f"properties for {event_name} must be exactly {sorted(allowed)}")
        row = AnalyticsEvent(event_name=event_name, properties=dict(properties))
        self._session.add(row)
        self._session.flush()
        return row
