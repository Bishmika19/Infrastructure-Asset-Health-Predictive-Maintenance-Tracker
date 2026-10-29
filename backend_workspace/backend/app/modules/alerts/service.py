"""Alert episode lifecycle and the maintenance queue (FR-4, DEC-09, DEC-07)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.unit_of_work import run_in_transaction
from app.infrastructure.outbox.writer import EVENT_ASSET_FLAGGED_EMAIL, OutboxWriter
from app.modules.alerts.repository import AlertRepository
from app.modules.analytics.emitter import ASSET_FLAGGED, AnalyticsEmitter
from app.modules.assets.models import Asset
from app.modules.audit.writer import EVENT_ALERT_OPENED, EVENT_ALERT_RESOLVED, AuditWriter
from app.modules.scoring.domain import is_flag_score
from app.modules.scoring.models import HealthScoreHistory
from app.shared.pagination import DEFAULT_PAGE_LIMIT, decode_cursor, encode_cursor
from app.shared.principal import Actor

QUEUE_CURSOR_KIND = "maintenance-queue"


@dataclass(frozen=True)
class QueueItem:
    """One flagged asset in the maintenance queue."""

    asset: Asset
    alert_id: Optional[uuid.UUID]


@dataclass(frozen=True)
class QueuePage:
    """A page of queue items and the cursor for the next page."""

    items: List[QueueItem]
    next_cursor: Optional[str]


class AlertService:
    """Open and close flag episodes inside the scoring caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = AlertRepository(session)

    # PUBLIC_INTERFACE
    def reconcile(
        self, asset: Asset, score: HealthScoreHistory, actor: Actor, now: dt.datetime
    ) -> None:
        """Open an episode below 40, close it at 40 or above; idempotent otherwise.

        The asset row must already be locked by the caller. ``asset.flagged_since`` is
        set on open and cleared on close so the queue index stays consistent.
        """
        open_alert = self._repo.get_open(asset.asset_id, lock=True)
        flagged = is_flag_score(score.score)
        if flagged and open_alert is None:
            alert = self._repo.add(asset.asset_id, score.id, score.score, now, actor.id)
            asset.flagged_since = now
            OutboxWriter(self._session).enqueue(
                EVENT_ASSET_FLAGGED_EMAIL,
                "asset",
                asset.asset_id,
                {
                    "assetId": asset.asset_id,
                    "alertId": str(alert.id),
                    "score": str(score.score),
                    "flaggedAt": now.isoformat(),
                },
            )
            AuditWriter(self._session).record(
                EVENT_ALERT_OPENED,
                actor,
                entity_type="alert",
                entity_id=str(alert.id),
                metadata={"assetId": asset.asset_id, "score": str(score.score)},
            )
            AnalyticsEmitter(self._session).emit(
                ASSET_FLAGGED, {"asset_id": asset.asset_id, "score_at_flag": str(score.score)}
            )
        elif flagged and open_alert is not None:
            asset.flagged_since = asset.flagged_since or open_alert.flagged_at
        elif not flagged and open_alert is not None:
            open_alert.resolved_at = now
            open_alert.resolved_score_id = score.id
            asset.flagged_since = None
            AuditWriter(self._session).record(
                EVENT_ALERT_RESOLVED,
                actor,
                entity_type="alert",
                entity_id=str(open_alert.id),
                metadata={"assetId": asset.asset_id, "score": str(score.score)},
            )
        else:
            asset.flagged_since = None
        self._session.flush()


class QueueService:
    """Read-only maintenance queue with signed keyset paging."""

    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        self._settings = settings
        self._factory = factory

    # PUBLIC_INTERFACE
    def list_queue(self, limit: int = DEFAULT_PAGE_LIMIT, cursor: Optional[str] = None) -> QueuePage:
        """Return flagged active assets ordered by score, flagged-since, then asset ID.

        Raises:
            InvalidCursor: the cursor is invalid for this list (422).
        """
        after = None
        if cursor:
            last = decode_cursor(self._settings.auth_token_secret, cursor, QUEUE_CURSOR_KIND, {})["last"]
            try:
                after = [
                    Decimal(last[0]),
                    dt.datetime.fromisoformat(last[1]),
                    str(last[2]),
                ]
            except (ValueError, TypeError, IndexError, ArithmeticError):
                from app.core.errors import InvalidCursor

                raise InvalidCursor() from None

        def work(session: Session) -> QueuePage:
            rows = AlertRepository(session).queue_page(after, limit + 1)
            page = rows[:limit]
            items = [QueueItem(asset=a, alert_id=alert_id) for a, alert_id in page]
            next_cursor = None
            if len(rows) > limit and page:
                tail = page[-1][0]
                assert tail.current_health_score is not None and tail.flagged_since is not None
                next_cursor = encode_cursor(
                    self._settings.auth_token_secret,
                    QUEUE_CURSOR_KIND,
                    [str(tail.current_health_score), tail.flagged_since.isoformat(), tail.asset_id],
                    {},
                )
            return QueuePage(items=items, next_cursor=next_cursor)

        return run_in_transaction(self._factory, work)
