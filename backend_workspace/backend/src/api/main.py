"""Manifest launcher ``uvicorn src.api.main:app``; re-exports ``app.main``."""

from app.main import app, create_app

__all__ = ["app", "create_app"]
