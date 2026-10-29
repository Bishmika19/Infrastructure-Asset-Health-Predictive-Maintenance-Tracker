"""``audit_logs`` table owned by the audit module (append-only)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Audit record for security- and business-relevant events (A-19)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("actor_kind IN ('user', 'system', 'anonymous')", name="actor_kind_allowed"),
        CheckConstraint("length(btrim(event_type)) > 0", name="event_type_nonblank"),
        CheckConstraint("length(btrim(request_id)) > 0", name="request_id_nonblank"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_audit_logs_occurred", "occurred_at", "id"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id", "occurred_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    actor_kind: Mapped[str] = mapped_column(Text)
    attempted_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    entity_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ``metadata`` is reserved on declarative classes, so the attribute is renamed.
    event_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSONB)
    request_id: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
