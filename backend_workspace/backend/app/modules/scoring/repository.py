"""Persistence for score calculations; never commits."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assets.models import Asset
from app.modules.inspections.models import Inspection
from app.modules.scoring.models import HealthScoreHistory


class ScoringRepository:
    """Data access used by ``ScoringService``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def lock_asset(self, asset_id: str) -> Optional[Asset]:
        """Load the asset with ``SELECT ... FOR UPDATE`` and fresh column values."""
        return self._session.execute(
            select(Asset).where(Asset.asset_id == asset_id).with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def latest_rating(self, asset_id: str) -> Optional[str]:
        """Condition rating of the asset's most recent inspection, if any."""
        return self._session.execute(
            select(Inspection.condition_rating)
            .where(Inspection.asset_id == asset_id)
            .order_by(Inspection.inspected_at.desc(), Inspection.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def add_history(
        self,
        asset_id: str,
        score: Decimal,
        band: str,
        trigger_type: str,
        formula_version: str,
        inputs: Dict[str, Any],
        calculated_at: dt.datetime,
        inspection_id: Optional[uuid.UUID],
        actor_id: Optional[uuid.UUID],
        run_id: Optional[uuid.UUID],
    ) -> HealthScoreHistory:
        """Insert an immutable calculation row and flush it."""
        row = HealthScoreHistory(
            asset_id=asset_id,
            score=score,
            color_band=band,
            trigger_type=trigger_type,
            formula_version=formula_version,
            inputs=inputs,
            calculated_at=calculated_at,
            inspection_id=inspection_id,
            actor_id=actor_id,
            run_id=run_id,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_for_asset(self, asset_id: str, limit: int) -> List[HealthScoreHistory]:
        """Most recent calculations for an asset (newest first)."""
        return list(
            self._session.execute(
                select(HealthScoreHistory)
                .where(HealthScoreHistory.asset_id == asset_id)
                .order_by(HealthScoreHistory.calculated_at.desc(), HealthScoreHistory.id.desc())
                .limit(limit)
            ).scalars()
        )

    def previous_score(self, asset: Asset) -> Tuple[Optional[Decimal], Optional[str]]:
        """Current stored score and band before a recalculation."""
        return asset.current_health_score, asset.current_color_band
