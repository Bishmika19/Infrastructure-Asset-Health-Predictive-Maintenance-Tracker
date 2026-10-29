"""Structured JSON logging with request and actor correlation."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Optional

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
actor_id_var: ContextVar[Optional[str]] = ContextVar("actor_id", default=None)


class _ContextFilter(logging.Filter):
    """Attach request_id and actor_id from context variables to each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.actor_id = actor_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "actor_id": getattr(record, "actor_id", None),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# PUBLIC_INTERFACE
def configure_logging(level: str = "info") -> None:
    """Configure root logging once with the JSON formatter and context filter."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    if any(getattr(h, "_asset_health", False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_ContextFilter())
    handler._asset_health = True  # type: ignore[attr-defined]
    root.addHandler(handler)
