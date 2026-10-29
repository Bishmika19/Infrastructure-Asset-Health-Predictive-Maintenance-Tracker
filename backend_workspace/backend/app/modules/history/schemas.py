"""Asset-history API schemas (FR-7, AC-09)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, Literal, Optional

from pydantic import Field

from app.shared.schema_base import ApiResponseModel

HistoryEventKind = Literal[
    "inspection_logged",
    "alert_opened",
    "alert_resolved",
    "work_order_status_changed",
]


class AssetHistoryEvent(ApiResponseModel):
    """One immutable inspection, alert, or work-order timeline event."""

    event_id: uuid.UUID = Field(..., description="Stable source-record identifier for the event.")
    event_kind: HistoryEventKind = Field(
        ..., description="Specific inspection, alert, or work-order event type."
    )
    occurred_at: dt.datetime = Field(..., description="UTC timestamp at which the event occurred.")
    actor_id: Optional[uuid.UUID] = Field(
        None, description="Responsible user ID; omitted only for system-originated events."
    )
    details: Dict[str, Any] = Field(
        ..., description="Allow-listed source-specific event details for rendering the timeline."
    )


class AssetHistoryPage(ApiResponseModel):
    """Chronological keyset-paginated history for one asset."""

    items: list[AssetHistoryEvent] = Field(
        ..., description="Events ordered by occurredAt, eventKind, and eventId ascending."
    )
    next_cursor: Optional[str] = Field(
        None, description="Signed cursor for the next chronological timeline page."
    )
