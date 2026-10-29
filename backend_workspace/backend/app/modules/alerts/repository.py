"""Persistence for alert episodes and the maintenance queue; never commits."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.modules.alerts.models import Alert
from app.modules.assets.models import Asset


class AlertRepository:
    """Data access for ``alerts`` and the queue projection over ``assets``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_open(self, asset_id: str, lock: bool = False) -> Optional[Alert]:
        """Return the unresolved episode for an asset, if any."""
        statement = select(Alert).where(Alert.asset_id == asset_id, Alert.resolved_at.is_(None))
        if lock:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def get(self, alert_id: uuid.UUID) -> Optional[Alert]:
        """Fetch an alert by primary key."""
        return self._session.get(Alert, alert_id)

    def add(
        self,
        asset_id: str,
        opening_score_id: uuid.UUID,
        score_at_flag: Decimal,
        flagged_at: dt.datetime,
        actor_id: Optional[uuid.UUID],
    ) -> Alert:
        """Open a new episode and flush it."""
        alert = Alert(
            asset_id=asset_id,
            opening_score_id=opening_score_id,
            score_at_flag=score_at_flag,
            flagged_at=flagged_at,
            actor_id=actor_id,
        )
        self._session.add(alert)
        self._session.flush()
        return alert

    def queue_page(
        self, after: Optional[Sequence[object]], limit: int
    ) -> List[Tuple[Asset, Optional[uuid.UUID]]]:
        """Return up to ``limit`` queue rows (asset, open alert id) after the keyset tuple.

        Order (DEC-09): score ascending, ``flagged_since`` ascending, asset ID ascending.
        """
        statement = (
            select(Asset, Alert.id)
            .outerjoin(Alert, (Alert.asset_id == Asset.asset_id) & Alert.resolved_at.is_(None))
            .where(Asset.status == "active", Asset.flagged_since.is_not(None))
            .order_by(Asset.current_health_score, Asset.flagged_since, Asset.asset_id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                tuple_(Asset.current_health_score, Asset.flagged_since, Asset.asset_id)
                > tuple_(*after)
            )
        return [(row[0], row[1]) for row in self._session.execute(statement).all()]
