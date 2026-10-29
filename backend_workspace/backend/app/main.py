"""Canonical FastAPI entrypoint: ``uvicorn app.main:app``.

The manifest launcher ``src.api.main:app`` re-exports ``app`` from here.
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from app.api.health import build_health_router
from app.api.v1 import build_api_v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestGuardMiddleware
from app.core.problem import register_problem_handlers
from app.db import registry as _model_registry  # noqa: F401 - registers all ORM mappings.
from app.db.session import database_is_usable

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness and readiness checks."},
    {"name": "identity", "description": "Login and the current user (bearer-token sessions)."},
    {
        "name": "assets",
        "description": "Asset register CRUD and current health-score snapshots.",
    },
    {
        "name": "alerts",
        "description": "Predictive alert episodes and the ordered maintenance queue.",
    },
    {
        "name": "inspections",
        "description": "Crew inspection logging, verified photo metadata, and inspection history.",
    },
    {
        "name": "cases",
        "description": "Manager-created maintenance work orders exposed exclusively as Cases.",
    },
    {
        "name": "history",
        "description": "Authenticated chronological asset timelines over inspections, alerts, and Cases.",
    },
]


# PUBLIC_INTERFACE
def create_app(
    settings: Optional[Settings] = None,
    db_probe: Optional[Callable[[], bool]] = None,
    session_factory: Optional[sessionmaker[Session]] = None,
) -> FastAPI:
    """Create the FastAPI application.

    Parameters:
        settings: Optional settings override (used by tests); defaults to the
            environment-derived settings.
        db_probe: Optional readiness probe override; defaults to a ``SELECT 1``
            through the runtime-role engine.
        session_factory: Optional session factory override (tests); defaults to the
            runtime-role factory resolved lazily per request.

    Returns:
        A configured FastAPI instance with CORS, request guards, problem+json
        handlers, health routes and the ``/api/v1`` router.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    probe = db_probe or (lambda: database_is_usable(settings))

    application = FastAPI(
        title="Infrastructure Asset Health & Predictive Maintenance Tracker API",
        description=(
            "HTTP/JSON API for asset registration, health scoring, inspections, "
            "predictive alerts, work orders and asset history."
        ),
        version="0.1.0",
        openapi_tags=OPENAPI_TAGS,
    )
    application.state.settings = settings
    application.state.session_factory = session_factory

    application.add_middleware(
        RequestGuardMiddleware,
        max_json_bytes=settings.max_json_body_bytes,
        max_multipart_bytes=settings.max_multipart_body_bytes,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=settings.allowed_methods,
        allow_headers=settings.allowed_headers,
        max_age=settings.cors_max_age,
    )
    register_problem_handlers(application)

    application.include_router(build_health_router(settings, probe))
    application.include_router(build_api_v1_router())
    return application


app = create_app()
