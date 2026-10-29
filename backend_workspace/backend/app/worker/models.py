"""``scheduled_runs`` table: durable, leased job schedule owned by the worker."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScheduledRun(Base):
    """One scheduled job occurrence with lease ownership and a fencing token."""

    __tablename__ = "scheduled_runs"
    __table_args__ = (
        UniqueConstraint("job_name", "scheduled_for", name="uq_scheduled_runs_identity"),
        CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed')", name="status_allowed"
        ),
        CheckConstraint("fencing_token > 0", name="fencing_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_name: Mapped[str] = mapped_column(Text)
    scheduled_for: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    cursor: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lease_until: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fencing_token: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
