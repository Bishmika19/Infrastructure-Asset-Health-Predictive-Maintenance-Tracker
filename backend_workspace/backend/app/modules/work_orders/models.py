"""``work_orders`` and ``work_order_status_history`` tables."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUS_SQL = "('Open', 'Assigned', 'In Progress', 'Complete')"


class WorkOrder(Base):
    """Maintenance work order with an immutable asset snapshot."""

    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(f"status IN {STATUS_SQL}", name="status_allowed"),
        CheckConstraint("priority IN ('Low', 'Medium', 'High', 'Critical')", name="priority_allowed"),
        CheckConstraint("length(btrim(fault_description)) > 0", name="fault_nonblank"),
        CheckConstraint("status = 'Open' OR assignee_id IS NOT NULL", name="assignee_required"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("jsonb_typeof(asset_snapshot) = 'object'", name="snapshot_object"),
        Index("ix_work_orders_recent", desc("created_at"), desc("id")),
        Index("ix_work_orders_asset_recent", "asset_id", desc("created_at"), desc("id")),
        Index(
            "ix_work_orders_assignee_recent",
            "assignee_id",
            "status",
            desc("created_at"),
            desc("id"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    asset_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("assets.asset_id", ondelete="RESTRICT")
    )
    alert_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=True
    )
    asset_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    fault_description: Mapped[str] = mapped_column(String(4000))
    priority: Mapped[str] = mapped_column(Text)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default="Open")
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    version: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))


class WorkOrderStatusHistory(Base):
    """Append-only lifecycle row written in the same transaction as the order."""

    __tablename__ = "work_order_status_history"
    __table_args__ = (
        UniqueConstraint("work_order_id", "order_version", name="uq_wo_status_history_version"),
        CheckConstraint(f"new_status IN {STATUS_SQL}", name="new_status_allowed"),
        CheckConstraint(
            f"previous_status IS NULL OR previous_status IN {STATUS_SQL}",
            name="previous_status_allowed",
        ),
        CheckConstraint("order_version > 0", name="order_version_positive"),
        Index("ix_wo_status_history_timeline", "work_order_id", "changed_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("work_orders.id", ondelete="RESTRICT")
    )
    previous_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_status: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    order_version: Mapped[int] = mapped_column(BigInteger)
