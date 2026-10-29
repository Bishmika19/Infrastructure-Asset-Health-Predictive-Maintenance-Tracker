"""``inspections`` and ``inspection_photos`` tables owned by the inspections module."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    desc,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAX_PHOTO_BYTES = 10_000_000  # A-12, decimal MB (provisional, OD-06)


class Inspection(Base):
    """Field inspection of an asset."""

    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint(
            "condition_rating IN ('Excellent', 'Good', 'Fair', 'Poor', 'Critical')",
            name="rating_allowed",
        ),
        CheckConstraint("length(btrim(observations)) > 0", name="observations_nonblank"),
        Index("ix_inspections_asset_latest", "asset_id", desc("inspected_at"), desc("id")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("assets.asset_id", ondelete="RESTRICT")
    )
    condition_rating: Mapped[str] = mapped_column(Text)
    observations: Mapped[str] = mapped_column(Text)
    inspector_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    inspected_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InspectionPhoto(Base):
    """Verified stored photo belonging to an inspection."""

    __tablename__ = "inspection_photos"
    __table_args__ = (
        CheckConstraint("content_type IN ('image/jpeg', 'image/png')", name="content_type_allowed"),
        CheckConstraint(f"size_bytes > 0 AND size_bytes <= {MAX_PHOTO_BYTES}", name="size_range"),
        CheckConstraint("length(btrim(checksum)) > 0", name="checksum_nonblank"),
        Index("ix_inspection_photos_inspection_id", "inspection_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("inspections.id", ondelete="RESTRICT")
    )
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    uploaded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    checksum: Mapped[str] = mapped_column(Text)
