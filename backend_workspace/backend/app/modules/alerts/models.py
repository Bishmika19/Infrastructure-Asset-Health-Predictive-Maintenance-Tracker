"""``alerts`` table owned by the alerts module (one row per flag episode)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Alert(Base):
    """Flag episode: opens below 40, closes (never deleted) at 40 or above."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("score_at_flag >= 0 AND score_at_flag < 40", name="flag_score_range"),
        CheckConstraint("resolved_at IS NULL OR resolved_at >= flagged_at", name="resolved_order"),
        CheckConstraint(
            "(resolved_at IS NULL) = (resolved_score_id IS NULL)", name="resolution_pair"
        ),
        # At most one unresolved episode per asset.
        Index(
            "uq_alerts_open_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index("ix_alerts_asset_flagged", "asset_id", "flagged_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("assets.asset_id", ondelete="RESTRICT")
    )
    opening_score_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("health_score_history.id", ondelete="RESTRICT")
    )
    score_at_flag: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    flagged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_score_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("health_score_history.id", ondelete="RESTRICT"), nullable=True
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
