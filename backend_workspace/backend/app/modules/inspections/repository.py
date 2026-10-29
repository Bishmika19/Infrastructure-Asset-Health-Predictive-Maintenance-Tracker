"""Persistence operations for inspections and their verified photo metadata."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import List, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.inspections.models import Inspection, InspectionPhoto


class InspectionRepository:
    """Data access for inspection and inspection-photo records; never commits."""

    def __init__(self, session: Session) -> None:
        """Store the caller-owned SQLAlchemy session."""
        self._session = session

    def add(
        self,
        asset_id: str,
        condition_rating: str,
        observations: str,
        inspector_id: uuid.UUID,
        inspected_at: dt.datetime,
    ) -> Inspection:
        """Insert and flush one inspection so dependent rows can reference its ID."""
        inspection = Inspection(
            asset_id=asset_id,
            condition_rating=condition_rating,
            observations=observations,
            inspector_id=inspector_id,
            inspected_at=inspected_at,
        )
        self._session.add(inspection)
        self._session.flush()
        return inspection

    def add_photo(self, inspection_id: uuid.UUID, storage_key: str, content_type: str, size_bytes: int,
                  checksum: str) -> InspectionPhoto:
        """Insert and flush verified metadata for a single staged photo."""
        photo = InspectionPhoto(
            inspection_id=inspection_id,
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=checksum,
        )
        self._session.add(photo)
        self._session.flush()
        return photo

    def list_page(
        self,
        asset_id: str,
        after: Optional[tuple[dt.datetime, uuid.UUID]],
        limit: int,
    ) -> List[Inspection]:
        """Return inspections newest first, after an optional descending keyset."""
        statement = select(Inspection).where(Inspection.asset_id == asset_id)
        if after is not None:
            inspected_at, inspection_id = after
            statement = statement.where(
                or_(
                    Inspection.inspected_at < inspected_at,
                    (Inspection.inspected_at == inspected_at) & (Inspection.id < inspection_id),
                )
            )
        statement = statement.order_by(Inspection.inspected_at.desc(), Inspection.id.desc()).limit(limit)
        return list(self._session.execute(statement).scalars())

    def photos_for_inspections(self, inspection_ids: Sequence[uuid.UUID]) -> List[InspectionPhoto]:
        """Return all photo metadata for the requested inspection IDs in a stable order."""
        if not inspection_ids:
            return []
        statement = (
            select(InspectionPhoto)
            .where(InspectionPhoto.inspection_id.in_(inspection_ids))
            .order_by(InspectionPhoto.uploaded_at, InspectionPhoto.id)
        )
        return list(self._session.execute(statement).scalars())
