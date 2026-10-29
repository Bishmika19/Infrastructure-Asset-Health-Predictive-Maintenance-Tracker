"""Inspection logging API schemas (FR-3, DEC-05)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal, Optional

from pydantic import Field

from app.shared.schema_base import ApiModel, ApiResponseModel

ConditionRating = Literal["Excellent", "Good", "Fair", "Poor", "Critical"]
MAX_PHOTOS_PER_INSPECTION = 10
MAX_PHOTO_BYTES = 10_000_000
INSPECTION_CURSOR_KIND = "asset-inspections"


class InspectionCreate(ApiModel):
    """Validated multipart form fields for one crew inspection."""

    condition_rating: ConditionRating = Field(..., description="Observed asset condition.")
    observations: str = Field(
        ..., min_length=1, max_length=4000, description="Crew observations recorded for the inspection."
    )


class InspectionPhotoOut(ApiResponseModel):
    """Verified non-public metadata for a photo attached to an inspection."""

    id: uuid.UUID = Field(..., description="Photo metadata identifier.")
    content_type: Literal["image/jpeg", "image/png"] = Field(..., description="Byte-sniffed media type.")
    size_bytes: int = Field(..., description="Verified byte length, at most 10,000,000.")
    checksum: str = Field(..., description="SHA-256 checksum of the staged image.")
    uploaded_at: dt.datetime = Field(..., description="Metadata creation time.")


class InspectionOut(ApiResponseModel):
    """One logged inspection with its verified photo metadata."""

    id: uuid.UUID = Field(..., description="Inspection identifier.")
    asset_id: str = Field(..., description="Asset inspected.")
    condition_rating: ConditionRating = Field(..., description="Observed asset condition.")
    observations: str = Field(..., description="Crew observations.")
    inspector_id: uuid.UUID = Field(..., description="Authenticated crew member who logged it.")
    inspected_at: dt.datetime = Field(..., description="Inspection timestamp.")
    created_at: dt.datetime = Field(..., description="Record creation timestamp.")
    photos: list[InspectionPhotoOut] = Field(..., description="Verified photo metadata in upload order.")


class InspectionPage(ApiResponseModel):
    """Keyset-paginated inspection history for one asset."""

    items: list[InspectionOut] = Field(..., description="Inspections newest first.")
    next_cursor: Optional[str] = Field(None, description="Signed cursor for the following page.")
