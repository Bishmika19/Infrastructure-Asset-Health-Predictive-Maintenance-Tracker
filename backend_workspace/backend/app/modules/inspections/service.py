"""Inspection application service: atomic records, scoring, and side effects."""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import Conflict, InvalidCursor, NotFound, ValidationFailed
from app.db.unit_of_work import run_in_transaction
from app.infrastructure.storage.base import StagedPhoto
from app.modules.analytics.emitter import INSPECTION_LOGGED, AnalyticsEmitter
from app.modules.assets.repository import AssetRepository
from app.modules.audit.writer import EVENT_INSPECTION_LOGGED, AuditWriter
from app.modules.inspections.models import Inspection, InspectionPhoto
from app.modules.inspections.repository import InspectionRepository
from app.modules.inspections.schemas import (
    INSPECTION_CURSOR_KIND,
    MAX_PHOTOS_PER_INSPECTION,
)
from app.modules.scoring.domain import TRIGGER_INSPECTION
from app.modules.scoring.service import ScoringService
from app.shared.pagination import DEFAULT_PAGE_LIMIT, decode_cursor, encode_cursor
from app.shared.principal import Principal


@dataclass(frozen=True)
class InspectionView:
    """Inspection ORM row paired with its ordered photo metadata."""

    inspection: Inspection
    photos: List[InspectionPhoto]


@dataclass(frozen=True)
class InspectionListPage:
    """Inspection views and an optional signed continuation cursor."""

    items: List[InspectionView]
    next_cursor: Optional[str]


class InspectionService:
    """Log crew inspections and query asset inspection history without FastAPI imports."""

    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        """Store request-independent settings and the runtime session factory."""
        self._settings = settings
        self._factory = factory

    # PUBLIC_INTERFACE
    def create(
        self,
        principal: Principal,
        asset_id: str,
        *,
        condition_rating: str,
        observations: str,
        photos: Sequence[StagedPhoto],
    ) -> InspectionView:
        """Atomically log one crew inspection, metadata, health score, and side effects.

        Storage bytes must have been staged and verified before this method is called.
        The caller promotes them only after this transaction commits.

        Raises:
            NotFound: no matching asset exists.
            Conflict: the asset is deactivated.
            ValidationFailed: the caller exceeds the maximum photo count.
        """
        if len(photos) > MAX_PHOTOS_PER_INSPECTION:
            raise ValidationFailed(f"At most {MAX_PHOTOS_PER_INSPECTION} photos are allowed")

        def work(session: Session) -> InspectionView:
            asset = AssetRepository(session).lock(asset_id)
            if asset is None:
                raise NotFound("Asset not found")
            if asset.status != "active":
                raise Conflict("Cannot log an inspection for a deactivated asset")

            now = dt.datetime.now(dt.timezone.utc)
            repository = InspectionRepository(session)
            inspection = repository.add(
                asset_id=asset_id,
                condition_rating=condition_rating,
                observations=observations,
                inspector_id=principal.user_id,
                inspected_at=now,
            )
            photo_rows = [
                repository.add_photo(
                    inspection.id,
                    storage_key=photo.storage_key,
                    content_type=photo.content_type,
                    size_bytes=photo.size_bytes,
                    checksum=photo.checksum,
                )
                for photo in photos
            ]
            ScoringService(session).recalculate(
                asset_id,
                TRIGGER_INSPECTION,
                principal.actor,
                inspection_id=inspection.id,
                now=now,
            )
            AuditWriter(session).record(
                EVENT_INSPECTION_LOGGED,
                principal.actor,
                entity_type="inspection",
                entity_id=str(inspection.id),
                metadata={"assetId": asset_id, "photoCount": len(photo_rows)},
            )
            AnalyticsEmitter(session).emit(
                INSPECTION_LOGGED,
                {
                    "asset_id": asset_id,
                    "condition_rating": condition_rating,
                    "photo_count": len(photo_rows),
                },
            )
            session.flush()
            return InspectionView(inspection=inspection, photos=photo_rows)

        return run_in_transaction(self._factory, work)

    # PUBLIC_INTERFACE
    def list(
        self,
        asset_id: str,
        *,
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: Optional[str] = None,
    ) -> InspectionListPage:
        """List one asset's inspection history newest first with signed keyset paging."""
        after = self._decode_cursor(asset_id, cursor) if cursor else None

        def work(session: Session) -> InspectionListPage:
            if AssetRepository(session).get(asset_id) is None:
                raise NotFound("Asset not found")
            repository = InspectionRepository(session)
            rows = repository.list_page(asset_id, after, limit + 1)
            page = rows[:limit]
            photos_by_inspection: Dict[uuid.UUID, List[InspectionPhoto]] = defaultdict(list)
            for photo in repository.photos_for_inspections([inspection.id for inspection in page]):
                photos_by_inspection[photo.inspection_id].append(photo)
            views = [
                InspectionView(inspection=inspection, photos=photos_by_inspection[inspection.id])
                for inspection in page
            ]
            next_cursor = None
            if len(rows) > limit and page:
                tail = page[-1]
                next_cursor = encode_cursor(
                    self._settings.auth_token_secret,
                    INSPECTION_CURSOR_KIND,
                    [tail.inspected_at.isoformat(), str(tail.id)],
                    {"assetId": asset_id},
                )
            return InspectionListPage(items=views, next_cursor=next_cursor)

        return run_in_transaction(self._factory, work)

    def _decode_cursor(
        self, asset_id: str, cursor: str
    ) -> tuple[dt.datetime, uuid.UUID]:
        """Decode and validate a cursor bound to the requested asset."""
        decoded = decode_cursor(
            self._settings.auth_token_secret,
            cursor,
            INSPECTION_CURSOR_KIND,
            {"assetId": asset_id},
        )
        try:
            timestamp, inspection_id = decoded["last"]
            return dt.datetime.fromisoformat(timestamp), uuid.UUID(inspection_id)
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidCursor() from error
