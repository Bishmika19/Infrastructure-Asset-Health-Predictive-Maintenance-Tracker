"""Read-only asset-history application service with transactional observability."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import InvalidCursor, NotFound
from app.db.unit_of_work import run_in_transaction
from app.modules.analytics.emitter import ASSET_HISTORY_VIEWED, AnalyticsEmitter
from app.modules.assets.repository import AssetRepository
from app.modules.audit.writer import EVENT_HISTORY_VIEWED, AuditWriter
from app.modules.history.repository import AssetHistoryRepository, TimelineSource
from app.shared.pagination import DEFAULT_PAGE_LIMIT, decode_cursor, encode_cursor
from app.shared.principal import Principal

ASSET_HISTORY_CURSOR_KIND = "asset-history"


@dataclass(frozen=True)
class AssetHistoryPageResult:
    """One chronological asset-history page and its optional continuation cursor."""

    items: list[TimelineSource]
    next_cursor: Optional[str]


class AssetHistoryService:
    """Serve the consolidated immutable timeline without importing FastAPI."""

    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        """Store request-independent settings and the database session factory."""
        self._settings = settings
        self._factory = factory

    # PUBLIC_INTERFACE
    def list(
        self,
        principal: Principal,
        asset_id: str,
        *,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> AssetHistoryPageResult:
        """Return one authenticated user's chronological asset-history page.

        Raises:
            NotFound: the asset does not exist.
            InvalidCursor: the signed cursor is malformed, tampered with, or belongs to
                a different asset history.
        """
        after = self._decode_cursor(asset_id, cursor) if cursor else None

        def work(session: Session) -> AssetHistoryPageResult:
            if AssetRepository(session).get(asset_id) is None:
                raise NotFound("Asset not found")

            rows = AssetHistoryRepository(session).list_page(asset_id, after, limit + 1)
            items = rows[:limit]
            next_cursor = None
            if len(rows) > limit and items:
                tail = items[-1]
                next_cursor = encode_cursor(
                    self._settings.auth_token_secret,
                    ASSET_HISTORY_CURSOR_KIND,
                    [tail.occurred_at.isoformat(), tail.event_kind, str(tail.event_id)],
                    {"assetId": asset_id},
                )

            AuditWriter(session).record(
                EVENT_HISTORY_VIEWED,
                principal.actor,
                entity_type="asset",
                entity_id=asset_id,
                metadata={"viewerRole": principal.role},
            )
            AnalyticsEmitter(session).emit(
                ASSET_HISTORY_VIEWED,
                {"asset_id": asset_id, "viewer_role": principal.role},
            )
            return AssetHistoryPageResult(items=items, next_cursor=next_cursor)

        return run_in_transaction(self._factory, work)

    def _decode_cursor(
        self, asset_id: str, cursor: str
    ) -> tuple[dt.datetime, str, uuid.UUID]:
        """Decode a cursor bound to the requested asset and its timeline ordering."""
        decoded = decode_cursor(
            self._settings.auth_token_secret,
            cursor,
            ASSET_HISTORY_CURSOR_KIND,
            {"assetId": asset_id},
        )
        try:
            occurred_at, event_kind, event_id = decoded["last"]
            if not isinstance(event_kind, str):
                raise TypeError("event kind must be text")
            return dt.datetime.fromisoformat(occurred_at), event_kind, uuid.UUID(event_id)
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidCursor() from error
