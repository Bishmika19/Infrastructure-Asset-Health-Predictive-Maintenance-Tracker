"""Read-only data projection for the consolidated asset-history timeline."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from sqlalchemy import Numeric, String, literal, select, tuple_, union_all
from sqlalchemy.orm import Session

from app.modules.alerts.models import Alert
from app.modules.inspections.models import Inspection
from app.modules.work_orders.models import WorkOrder, WorkOrderStatusHistory


@dataclass(frozen=True)
class TimelineSource:
    """One typed source row for the asset-history projection."""

    event_id: uuid.UUID
    event_kind: str
    occurred_at: dt.datetime
    actor_id: Optional[uuid.UUID]
    details: Dict[str, object]


class AssetHistoryRepository:
    """Project immutable timeline events from business records without writing data."""

    def __init__(self, session: Session) -> None:
        """Store the transaction-scoped SQLAlchemy session."""
        self._session = session

    def list_page(
        self,
        asset_id: str,
        after: Optional[Sequence[object]],
        limit: int,
    ) -> List[TimelineSource]:
        """Return timeline rows after an ascending `(time, kind, id)` keyset tuple."""
        timeline = union_all(
            select(
                Inspection.id.label("event_id"),
                literal("inspection_logged").label("event_kind"),
                Inspection.inspected_at.label("occurred_at"),
                Inspection.inspector_id.label("actor_id"),
                Inspection.condition_rating.label("condition_rating"),
                literal(None, type_=Numeric(5, 2)).label("alert_score"),
                literal(None, type_=String).label("previous_status"),
                literal(None, type_=String).label("new_status"),
            ).where(Inspection.asset_id == asset_id),
            select(
                Alert.id.label("event_id"),
                literal("alert_opened").label("event_kind"),
                Alert.flagged_at.label("occurred_at"),
                Alert.actor_id.label("actor_id"),
                literal(None, type_=String).label("condition_rating"),
                Alert.score_at_flag.label("alert_score"),
                literal(None, type_=String).label("previous_status"),
                literal(None, type_=String).label("new_status"),
            ).where(Alert.asset_id == asset_id),
            select(
                Alert.id.label("event_id"),
                literal("alert_resolved").label("event_kind"),
                Alert.resolved_at.label("occurred_at"),
                Alert.actor_id.label("actor_id"),
                literal(None, type_=String).label("condition_rating"),
                literal(None, type_=Numeric(5, 2)).label("alert_score"),
                literal(None, type_=String).label("previous_status"),
                literal(None, type_=String).label("new_status"),
            ).where(Alert.asset_id == asset_id, Alert.resolved_at.is_not(None)),
            select(
                WorkOrderStatusHistory.id.label("event_id"),
                literal("work_order_status_changed").label("event_kind"),
                WorkOrderStatusHistory.changed_at.label("occurred_at"),
                WorkOrderStatusHistory.actor_id.label("actor_id"),
                literal(None, type_=String).label("condition_rating"),
                literal(None, type_=Numeric(5, 2)).label("alert_score"),
                WorkOrderStatusHistory.previous_status.label("previous_status"),
                WorkOrderStatusHistory.new_status.label("new_status"),
            )
            .join(WorkOrder, WorkOrderStatusHistory.work_order_id == WorkOrder.id)
            .where(WorkOrder.asset_id == asset_id),
        ).subquery("asset_history")

        statement = (
            select(timeline)
            .order_by(timeline.c.occurred_at, timeline.c.event_kind, timeline.c.event_id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                tuple_(timeline.c.occurred_at, timeline.c.event_kind, timeline.c.event_id)
                > tuple_(*after)
            )

        return [
            TimelineSource(
                event_id=row.event_id,
                event_kind=row.event_kind,
                occurred_at=row.occurred_at,
                actor_id=row.actor_id,
                details=self._details(
                    row.event_kind,
                    row.condition_rating,
                    row.alert_score,
                    row.previous_status,
                    row.new_status,
                ),
            )
            for row in self._session.execute(statement)
        ]

    @staticmethod
    def _details(
        event_kind: str,
        condition_rating: Optional[str],
        alert_score: Optional[Decimal],
        previous_status: Optional[str],
        new_status: Optional[str],
    ) -> Dict[str, object]:
        """Map source-specific columns to the allow-listed timeline detail object."""
        if event_kind == "inspection_logged":
            return {"conditionRating": condition_rating}
        if event_kind == "alert_opened":
            return {"scoreAtFlag": alert_score}
        if event_kind == "alert_resolved":
            return {}
        return {
            "previousStatus": previous_status,
            "newStatus": new_status,
        }
