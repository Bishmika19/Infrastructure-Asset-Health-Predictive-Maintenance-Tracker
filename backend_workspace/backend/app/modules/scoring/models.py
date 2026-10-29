"""``health_score_history`` table owned by the scoring module."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

BAND_SQL = (
    "(color_band = 'Green' AND score >= 70) OR "
    "(color_band = 'Amber' AND score >= 40 AND score < 70) OR "
    "(color_band = 'Red' AND score < 40)"
)


class HealthScoreHistory(Base):
    """Immutable score calculation with reproducible inputs and provenance."""

    __tablename__ = "health_score_history"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint(BAND_SQL, name="band_consistent"),
        CheckConstraint(
            "trigger_type IN ('asset_create', 'inspection', 'service_update', "
            "'asset_update', 'nightly')",
            name="trigger_allowed",
        ),
        CheckConstraint("jsonb_typeof(inputs) = 'object'", name="inputs_object"),
        Index("ix_health_score_history_asset_time", "asset_id", "calculated_at", "id"),
        Index(
            "uq_health_score_history_run_asset",
            "run_id",
            "asset_id",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("assets.asset_id", ondelete="RESTRICT")
    )
    inspection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("inspections.id", ondelete="RESTRICT"), nullable=True
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    color_band: Mapped[str] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(Text)
    formula_version: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    calculated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("scheduled_runs.id", ondelete="RESTRICT"), nullable=True
    )
