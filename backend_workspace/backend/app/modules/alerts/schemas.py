"""Maintenance-queue API response schemas (FR-4, DEC-09)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal, Optional

from pydantic import Field

from app.shared.schema_base import ApiResponseModel

ColorBand = Literal["Green", "Amber", "Red"]


class MaintenanceQueueItem(ApiResponseModel):
    """A flagged active asset ordered for maintenance attention."""

    alert_id: uuid.UUID = Field(..., description="Open alert episode identifier.")
    asset_id: str = Field(..., description="Lifetime-unique asset ID.")
    asset_type: str = Field(..., description="Infrastructure asset category.")
    location: str = Field(..., description="Human-readable asset site.")
    current_health_score: Decimal = Field(..., description="Current health score, below 40.")
    current_color_band: ColorBand = Field(..., description="Current score colour band.")
    flagged_since: dt.datetime = Field(..., description="When the unresolved alert episode opened.")


class MaintenanceQueuePage(ApiResponseModel):
    """A keyset-paginated maintenance queue response."""

    items: list[MaintenanceQueueItem] = Field(
        ..., description="Flagged active assets in operational priority order."
    )
    next_cursor: Optional[str] = Field(
        None, description="Signed cursor for the following page, when more rows exist."
    )
