"""``analytics_events`` table owned by the analytics module."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict

from sqlalchemy import CheckConstraint, DateTime, Index, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalyticsEvent(Base):
    """Allow-listed product analytics event (allow-list enforced by the emitter)."""

    __tablename__ = "analytics_events"
    __table_args__ = (
        CheckConstraint("length(btrim(event_name)) > 0", name="event_name_nonblank"),
        CheckConstraint("jsonb_typeof(properties) = 'object'", name="properties_object"),
        Index("ix_analytics_events_occurred", "occurred_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_name: Mapped[str] = mapped_column(Text)
    properties: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
