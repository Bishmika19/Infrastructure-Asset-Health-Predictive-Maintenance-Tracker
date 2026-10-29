"""Authenticated predictive-alert maintenance queue route (FR-4, DEC-09)."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.modules.alerts.schemas import MaintenanceQueueItem, MaintenanceQueuePage
from app.modules.alerts.service import QueueService
from app.shared.deps import get_principal, get_request_settings, get_session_factory_dep
from app.shared.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.shared.principal import Principal

router = APIRouter(tags=["alerts"])

_PROBLEM_RESPONSES = {
    400: {"description": "Unknown or repeated query parameter."},
    401: {"description": "Missing, expired, or invalid bearer token."},
    422: {"description": "The supplied maintenance-queue cursor is invalid."},
}


def _queue_service(
    settings: Settings = Depends(get_request_settings),
    factory: sessionmaker[Session] = Depends(get_session_factory_dep),
) -> QueueService:
    """Build the request-scoped, read-only maintenance queue service."""
    return QueueService(settings, factory)


@router.get(
    "/maintenance-queue",
    response_model=MaintenanceQueuePage,
    summary="List the maintenance queue",
    description=(
        "List active flagged assets in ascending health-score, flagged-since, and asset-ID "
        "order. The signed cursor preserves that deterministic operational ordering."
    ),
    operation_id="list_maintenance_queue",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
def list_maintenance_queue(
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_LIMIT, description="Maximum queue records to return.")
    ] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[
        Optional[str], Query(description="Signed cursor returned by a prior queue page.")
    ] = None,
    _: Principal = Depends(get_principal),
    service: QueueService = Depends(_queue_service),
) -> MaintenanceQueuePage:
    """Return the authenticated user's page of currently flagged active assets."""
    page = service.list_queue(limit=limit, cursor=cursor)
    return MaintenanceQueuePage(
        items=[
            MaintenanceQueueItem(
                alert_id=item.alert_id,
                asset_id=item.asset.asset_id,
                asset_type=item.asset.asset_type,
                location=item.asset.location,
                current_health_score=item.asset.current_health_score,
                current_color_band=item.asset.current_color_band,
                flagged_since=item.asset.flagged_since,
            )
            for item in page.items
            if item.alert_id is not None
            and item.asset.current_health_score is not None
            and item.asset.current_color_band is not None
            and item.asset.flagged_since is not None
        ],
        next_cursor=page.next_cursor,
    )
