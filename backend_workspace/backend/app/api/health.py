"""Health routes: liveness at ``/livez`` and readiness at ``HEALTHCHECK_PATH``."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.config import Settings


class HealthResponse(BaseModel):
    """Response body of the health checks."""

    status: str = Field(..., description="'ok' when healthy, 'unavailable' when not ready.")
    service: str = Field(..., description="Service name.")
    database: str = Field(..., description="Database check result: 'ok' or 'unavailable'.")


# PUBLIC_INTERFACE
def build_health_router(settings: Settings, db_probe: Callable[[], bool]) -> APIRouter:
    """Build the health router.

    Parameters:
        settings: Provides the configurable readiness path (``HEALTHCHECK_PATH``).
        db_probe: Returns True when the database is usable.

    Returns:
        A router with a liveness route and a readiness route that answers 503
        when the database is unusable.
    """
    router = APIRouter(tags=["health"])

    @router.get(
        "/livez",
        response_model=HealthResponse,
        summary="Liveness check",
        description="Returns 200 while the API process is running; does not touch the database.",
        operation_id="get_liveness",
    )
    def live() -> HealthResponse:
        """Liveness probe."""
        return HealthResponse(status="ok", service="backend", database="unchecked")

    @router.get(
        settings.healthcheck_path,
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse, "description": "Database unusable."}},
        summary="Readiness check",
        description="Returns 200 when the API and the database are usable, otherwise 503.",
        operation_id="get_health",
    )
    def ready():
        """Readiness probe: 503 when the database cannot be used."""
        if db_probe():
            return HealthResponse(status="ok", service="backend", database="ok")
        body = HealthResponse(status="unavailable", service="backend", database="unavailable")
        return JSONResponse(body.model_dump(), status_code=503)

    return router
