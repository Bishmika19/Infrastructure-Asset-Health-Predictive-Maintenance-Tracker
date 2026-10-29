"""Durable nightly score recalculation job (DEC-03, DEC-06)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.unit_of_work import run_in_transaction
from app.modules.assets.models import Asset
from app.modules.scoring.models import HealthScoreHistory
from app.modules.scoring.service import ScoringService
from app.shared.principal import SYSTEM_ACTOR
from app.worker.scheduler import ScheduledLease, Scheduler


class NightlyScoringJob:
    """Recalculate active assets in resumable keyset batches."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        scheduler: Scheduler,
        batch_size: int,
    ) -> None:
        """Create a job that records its keyset progress on the durable schedule row."""
        self._factory = factory
        self._scheduler = scheduler
        self._batch_size = max(1, batch_size)

    # PUBLIC_INTERFACE
    def run(self, lease: ScheduledLease) -> int:
        """Score all active assets after ``lease.cursor`` and return the processed count.

        Each asset is recalculated in its own short transaction. The scoring
        service locks and re-reads the asset, preventing stale batch data from
        replacing a newer event-driven score. The unique run/asset index and
        an existence check make recovery after a process crash idempotent.
        """
        cursor = lease.cursor
        processed = 0
        while True:
            asset_ids = run_in_transaction(
                self._factory,
                lambda session: self._next_asset_ids(session, cursor),
            )
            if not asset_ids:
                return processed
            for asset_id in asset_ids:
                if self._score_if_needed(lease, asset_id):
                    processed += 1
            cursor = asset_ids[-1]
            if not self._scheduler.checkpoint(lease, cursor):
                raise RuntimeError("nightly scoring lease was fenced before checkpoint")
            if not self._scheduler.renew(lease):
                raise RuntimeError("nightly scoring lease was fenced before completion")

    def _next_asset_ids(self, session: Session, after: Optional[str]) -> list[str]:
        """Read one deterministic active-asset keyset page without retaining locks."""
        statement = (
            select(Asset.asset_id)
            .where(Asset.status == "active")
            .order_by(Asset.asset_id)
            .limit(self._batch_size)
        )
        if after is not None:
            statement = statement.where(Asset.asset_id > after)
        return list(session.execute(statement).scalars())

    def _score_if_needed(self, lease: ScheduledLease, asset_id: str) -> bool:
        """Recalculate one asset unless a prior attempt already committed its run result."""
        def work(session: Session) -> bool:
            existing = session.execute(
                select(HealthScoreHistory.id).where(
                    HealthScoreHistory.run_id == lease.run_id,
                    HealthScoreHistory.asset_id == asset_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return False
            ScoringService(session).recalculate(
                asset_id,
                "nightly",
                actor=SYSTEM_ACTOR,
                run_id=lease.run_id,
            )
            return True

        return run_in_transaction(self._factory, work)
