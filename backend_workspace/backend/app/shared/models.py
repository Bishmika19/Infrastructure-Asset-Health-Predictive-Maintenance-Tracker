"""Technical table owned by shared/idempotency: ``idempotency_records``."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdempotencyRecord(Base):
    """Replayable response for a create keyed by (principal, operation, key)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint("response_status BETWEEN 100 AND 599", name="status_range"),
    )

    principal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    operation: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    response_body: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    response_headers: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    response_status: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
