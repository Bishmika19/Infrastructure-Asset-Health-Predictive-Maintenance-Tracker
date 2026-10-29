"""Freshness observations emitted by the worker (AC-15)."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.unit_of_work import run_in_transaction
from app.infrastructure.outbox.models import OutboxEvent
from app.worker.models import ScheduledRun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Freshness:
    """The latest completed nightly run and oldest undelivered outbox timestamp."""

    last_nightly_completed_at: Optional[dt.datetime]
    oldest_pending_outbox_at: Optional[dt.datetime]


class FreshnessReporter:
    """Read worker freshness data without mutating business state."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        """Create a reporter using the runtime-role session factory."""
        self._factory = factory

    # PUBLIC_INTERFACE
    def snapshot(self) -> Freshness:
        """Return current durable freshness observations."""
        def work(session: Session) -> Freshness:
            completed = session.execute(
                select(func.max(ScheduledRun.completed_at)).where(
                    ScheduledRun.job_name == "nightly_scoring",
                    ScheduledRun.status == "complete",
                )
            ).scalar_one()
            pending = session.execute(
                select(func.min(OutboxEvent.created_at)).where(
                    OutboxEvent.status.in_(("pending", "leased")),
                )
            ).scalar_one()
            return Freshness(completed, pending)

        return run_in_transaction(self._factory, work)

    # PUBLIC_INTERFACE
    def emit(self) -> Freshness:
        """Log one structured freshness observation and return it."""
        freshness = self.snapshot()
        logger.info(
            "worker_freshness last_nightly_completed_at=%s oldest_pending_outbox_at=%s",
            freshness.last_nightly_completed_at,
            freshness.oldest_pending_outbox_at,
        )
        return freshness
