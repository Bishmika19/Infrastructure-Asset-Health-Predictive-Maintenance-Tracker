"""At-least-once transactional-outbox dispatcher with fenced leases (DEC-07)."""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.unit_of_work import run_in_transaction
from app.infrastructure.outbox.models import OutboxEvent

logger = logging.getLogger(__name__)
UTC = dt.timezone.utc


class OutboxDeliverySuppressed(RuntimeError):
    """Signal that a leased event must be dead-lettered without external delivery."""


@dataclass(frozen=True)
class OutboxLease:
    """A leased outbox message safe to deliver outside the database transaction."""

    event_id: uuid.UUID
    event_type: str
    payload: dict[str, object]
    fencing_token: int


# PUBLIC_INTERFACE
def retry_delay_seconds(attempt: int, cap_seconds: int) -> int:
    """Return capped exponential retry delay for a one-based delivery failure count."""
    return min(max(1, cap_seconds), 5 * (2 ** max(0, attempt - 1)))


class OutboxDispatcher:
    """Lease pending events, deliver them externally, then apply fenced acknowledgements."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        owner: str,
        lease_seconds: int,
        max_attempts: int,
        backoff_cap_seconds: int,
        deliver: Callable[[OutboxLease], None],
    ) -> None:
        """Create a dispatcher with injected delivery for the supported event types."""
        self._factory = factory
        self._owner = owner
        self._lease_seconds = max(1, lease_seconds)
        self._max_attempts = max(1, max_attempts)
        self._backoff_cap_seconds = max(1, backoff_cap_seconds)
        self._deliver = deliver

    # PUBLIC_INTERFACE
    def dispatch(self, limit: int = 50, now: Optional[dt.datetime] = None) -> int:
        """Deliver up to ``limit`` available events and return the number acknowledged."""
        current = now or dt.datetime.now(UTC)
        delivered = 0
        for lease in self._lease_available(max(1, limit), current):
            try:
                # This call is intentionally outside the lease-claim transaction.
                self._deliver(lease)
            except OutboxDeliverySuppressed as error:
                logger.info("outbox delivery suppressed for event %s: %s", lease.event_id, error)
                self._mark_dead(lease)
            except Exception as error:  # noqa: BLE001 - delivery is isolated per event
                logger.warning("outbox delivery failed for event %s: %s", lease.event_id, error)
                self._record_failure(lease, current)
            else:
                if self._mark_delivered(lease, current):
                    delivered += 1
        return delivered

    def _lease_available(self, limit: int, now: dt.datetime) -> list[OutboxLease]:
        """Claim available or expired rows with ``SKIP LOCKED`` in one short transaction."""
        def work(session: Session) -> list[OutboxLease]:
            rows = list(
                session.execute(
                    select(OutboxEvent)
                    .where(
                        or_(
                            (OutboxEvent.status == "pending") & (OutboxEvent.available_at <= now),
                            (OutboxEvent.status == "leased") & (OutboxEvent.lease_until <= now),
                        )
                    )
                    .order_by(OutboxEvent.available_at, OutboxEvent.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                ).scalars()
            )
            leased: list[OutboxLease] = []
            for row in rows:
                row.status = "leased"
                row.lease_owner = self._owner
                row.lease_until = now + dt.timedelta(seconds=self._lease_seconds)
                row.fencing_token += 1
                leased.append(
                    OutboxLease(
                        event_id=row.id,
                        event_type=row.event_type,
                        payload=dict(row.payload),
                        fencing_token=row.fencing_token,
                    )
                )
            session.flush()
            return leased

        return run_in_transaction(self._factory, work)

    def _mark_delivered(self, lease: OutboxLease, now: dt.datetime) -> bool:
        """Acknowledge only a currently owned, unfenced leased row."""
        return self._mutate_owned(
            lease,
            {
                "status": "delivered",
                "delivered_at": now,
                "lease_owner": None,
                "lease_until": None,
            },
        )

    def _record_failure(self, lease: OutboxLease, now: dt.datetime) -> bool:
        """Count a failed delivery and schedule retry or dead-letter the event."""
        def work(session: Session) -> bool:
            row = session.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.id == lease.event_id,
                    OutboxEvent.status == "leased",
                    OutboxEvent.lease_owner == self._owner,
                    OutboxEvent.fencing_token == lease.fencing_token,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                return False
            row.attempts += 1
            row.lease_owner = None
            row.lease_until = None
            if row.attempts >= self._max_attempts:
                row.status = "dead"
            else:
                row.status = "pending"
                row.available_at = now + dt.timedelta(
                    seconds=retry_delay_seconds(row.attempts, self._backoff_cap_seconds)
                )
            session.flush()
            return True

        return run_in_transaction(self._factory, work)

    def _mark_dead(self, lease: OutboxLease) -> bool:
        """Dead-letter an intentionally suppressed event without retrying or sending it."""
        return self._mutate_owned(
            lease,
            {
                "status": "dead",
                "lease_owner": None,
                "lease_until": None,
            },
        )

    def _mutate_owned(self, lease: OutboxLease, values: dict[str, object]) -> bool:
        """Apply a conditional acknowledgement without ever re-delivering a fenced row."""
        def work(session: Session) -> bool:
            result = session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == lease.event_id,
                    OutboxEvent.status == "leased",
                    OutboxEvent.lease_owner == self._owner,
                    OutboxEvent.fencing_token == lease.fencing_token,
                )
                .values(**values)
            )
            return result.rowcount == 1

        return run_in_transaction(self._factory, work)
