"""Score recalculation inside the caller's unit of work (DEC-03, DEC-12)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.alerts.service import AlertService
from app.modules.analytics.emitter import HEALTH_SCORE_RECALCULATED, AnalyticsEmitter
from app.modules.audit.writer import EVENT_SCORE_RECALCULATED, AuditWriter
from app.modules.scoring.domain import (
    FORMULA_VERSION,
    ScoreInputs,
    compute_score,
    is_flag_score,
)
from app.modules.scoring.models import HealthScoreHistory
from app.modules.scoring.repository import ScoringRepository
from app.shared.principal import Actor


class ScoringService:
    """Lock the asset, compute, persist history, update the asset, reconcile alerts.

    Never commits and never imports FastAPI, so the nightly worker reuses it unchanged.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ScoringRepository(session)

    # PUBLIC_INTERFACE
    def recalculate(
        self,
        asset_id: str,
        trigger_type: str,
        actor: Actor,
        inspection_id: Optional[uuid.UUID] = None,
        run_id: Optional[uuid.UUID] = None,
        now: Optional[dt.datetime] = None,
    ) -> HealthScoreHistory:
        """Recalculate one asset from its *current* locked data and persist the result.

        Raises:
            NotFound: the asset does not exist.
        """
        now = now or dt.datetime.now(dt.timezone.utc)
        asset = self._repo.lock_asset(asset_id)
        if asset is None:
            raise NotFound("Asset not found")
        previous_score, _ = self._repo.previous_score(asset)
        result = compute_score(
            ScoreInputs(
                installation_date=asset.installation_date,
                last_service_date=asset.last_service_date,
                latest_rating=self._repo.latest_rating(asset.asset_id),
                calculated_on=now.date(),
            )
        )
        history = self._repo.add_history(
            asset_id=asset.asset_id,
            score=result.score,
            band=result.band,
            trigger_type=trigger_type,
            formula_version=FORMULA_VERSION,
            inputs=result.inputs,
            calculated_at=now,
            inspection_id=inspection_id,
            actor_id=actor.id,
            run_id=run_id,
        )
        # Clear the flag before the score update can autoflush.  Reconciliation queries the
        # current alert row, and PostgreSQL rejects an intermediate recovered score paired
        # with a stale flag timestamp under ``ck_assets_flag_requires_low_score``.
        if not is_flag_score(result.score):
            asset.flagged_since = None
        asset.current_health_score = result.score
        asset.current_color_band = result.band
        asset.score_calculated_at = now
        AlertService(self._session).reconcile(asset, history, actor, now)

        AuditWriter(self._session).record(
            EVENT_SCORE_RECALCULATED,
            actor,
            entity_type="asset",
            entity_id=asset.asset_id,
            metadata={"trigger": trigger_type, "score": str(result.score), "band": result.band},
        )
        AnalyticsEmitter(self._session).emit(
            HEALTH_SCORE_RECALCULATED,
            {
                "asset_id": asset.asset_id,
                "previous_score": str(previous_score) if previous_score is not None else None,
                "new_score": str(result.score),
                "color_band": result.band,
                "trigger_type": trigger_type,
            },
        )
        self._session.flush()
        return history
