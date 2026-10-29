"""Durable PostgreSQL schedule leases with fencing tokens (DEC-06)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.unit_of_work import run_in_transaction
from app.worker.models import ScheduledRun

UTC = dt.timezone.utc


@dataclass(frozen=True)
class ScheduledLease:
    """An owned, fenced scheduled-run lease."""

    run_id: uuid.UUID
    job_name: str
    scheduled_for: dt.datetime
    cursor: Optional[str]
    fencing_token: int


# PUBLIC_INTERFACE
def utc_day(value: Optional[dt.datetime] = None) -> dt.datetime:
    """Return the UTC-midnight occurrence containing ``value`` or the current time."""
    instant = (value or dt.datetime.now(UTC)).astimezone(UTC)
    return dt.datetime.combine(instant.date(), dt.time.min, tzinfo=UTC)


class Scheduler:
    """Claim, renew, checkpoint, and complete durable scheduled-job occurrences."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        owner: str,
        lease_seconds: int,
    ) -> None:
        """Create a scheduler with one stable worker identity."""
        self._factory = factory
        self._owner = owner
        self._lease_seconds = max(1, lease_seconds)

    # PUBLIC_INTERFACE
    def claim(
        self,
        job_name: str,
        scheduled_for: dt.datetime,
        now: Optional[dt.datetime] = None,
    ) -> Optional[ScheduledLease]:
        """Create or reclaim an occurrence and return its fenced lease.

        The advisory lock serializes create-or-claim decisions. A completed
        occurrence is never reclaimed; failed and expired occurrences resume
        from their durable keyset cursor.
        """
        current = now or dt.datetime.now(UTC)
        occurrence = scheduled_for.astimezone(UTC)

        def work(session: Session) -> Optional[ScheduledLease]:
            identity = f"{job_name}:{occurrence.isoformat()}"
            session.execute(select(func.pg_advisory_xact_lock(func.hashtext(identity))))
            row = session.execute(
                select(ScheduledRun)
                .where(
                    ScheduledRun.job_name == job_name,
                    ScheduledRun.scheduled_for == occurrence,
                )
                .with_for_update()
            ).scalar_one_or_none()

            if row is None:
                row = ScheduledRun(
                    job_name=job_name,
                    scheduled_for=occurrence,
                    status="running",
                    lease_owner=self._owner,
                    lease_until=self._lease_until(current),
                    fencing_token=1,
                    started_at=current,
                )
                session.add(row)
            else:
                if row.status == "complete":
                    return None
                if row.status == "running" and row.lease_until and row.lease_until > current:
                    return None
                row.status = "running"
                row.lease_owner = self._owner
                row.lease_until = self._lease_until(current)
                row.started_at = row.started_at or current
                row.fencing_token += 1

            session.flush()
            return ScheduledLease(
                run_id=row.id,
                job_name=row.job_name,
                scheduled_for=row.scheduled_for,
                cursor=row.cursor,
                fencing_token=row.fencing_token,
            )

        return run_in_transaction(self._factory, work)

    # PUBLIC_INTERFACE
    def renew(self, lease: ScheduledLease, now: Optional[dt.datetime] = None) -> bool:
        """Extend an owned lease; return False when a newer worker fenced it."""
        return self._update_owned(lease, now or dt.datetime.now(UTC), {})

    # PUBLIC_INTERFACE
    def checkpoint(
        self,
        lease: ScheduledLease,
        cursor: str,
        now: Optional[dt.datetime] = None,
    ) -> bool:
        """Persist a resumable cursor while renewing an owned lease."""
        return self._update_owned(
            lease,
            now or dt.datetime.now(UTC),
            {"cursor": cursor},
        )

    # PUBLIC_INTERFACE
    def complete(self, lease: ScheduledLease, now: Optional[dt.datetime] = None) -> bool:
        """Mark an owned occurrence complete and release its lease."""
        current = now or dt.datetime.now(UTC)
        return self._update_owned(
            lease,
            current,
            {
                "status": "complete",
                "completed_at": current,
                "lease_owner": None,
                "lease_until": None,
            },
        )

    # PUBLIC_INTERFACE
    def fail(self, lease: ScheduledLease, now: Optional[dt.datetime] = None) -> bool:
        """Release a failed occurrence for a later worker to resume."""
        return self._update_owned(
            lease,
            now or dt.datetime.now(UTC),
            {"status": "failed", "lease_owner": None, "lease_until": None},
        )

    def _update_owned(
        self,
        lease: ScheduledLease,
        now: dt.datetime,
        values: dict[str, object],
    ) -> bool:
        """Apply a short fenced mutation to an owned schedule row."""
        mutation = {"lease_until": self._lease_until(now), **values}

        def work(session: Session) -> bool:
            result = session.execute(
                update(ScheduledRun)
                .where(
                    ScheduledRun.id == lease.run_id,
                    ScheduledRun.status == "running",
                    ScheduledRun.lease_owner == self._owner,
                    ScheduledRun.fencing_token == lease.fencing_token,
                )
                .values(**mutation)
            )
            return result.rowcount == 1

        return run_in_transaction(self._factory, work)

    def _lease_until(self, now: dt.datetime) -> dt.datetime:
        """Calculate the bounded expiry for a lease renewal."""
        return now + dt.timedelta(seconds=self._lease_seconds)
