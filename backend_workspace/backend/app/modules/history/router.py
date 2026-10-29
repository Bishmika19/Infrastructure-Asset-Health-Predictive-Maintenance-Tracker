"""Authenticated read-only asset-history API route (FR-7)."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.modules.history.schemas import AssetHistoryEvent, AssetHistoryPage
from app.modules.history.service import AssetHistoryService
from app.shared.deps import get_principal, get_request_settings, get_session_factory_dep
from app.shared.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.shared.principal import Principal

router = APIRouter(prefix="/assets/{asset_id}/history", tags=["history"])

_PROBLEM_RESPONSES = {
    400: {"description": "Unknown or repeated query parameter."},
    401: {"description": "Missing, expired, or invalid bearer token."},
    404: {"description": "Asset does not exist."},
    422: {"description": "Known query value or signed cursor is invalid."},
}


def _service(
    settings: Settings = Depends(get_request_settings),
    factory: sessionmaker[Session] = Depends(get_session_factory_dep),
) -> AssetHistoryService:
    """Build the request-scoped asset-history application service."""
    return AssetHistoryService(settings, factory)


@router.get(
    "",
    response_model=AssetHistoryPage,
    summary="Get asset history",
    description=(
        "Return a single chronological, read-only timeline of inspections, alert "
        "openings/resolutions, and Case status changes for one authenticated asset view."
    ),
    operation_id="get_asset_history",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
def get_asset_history(
    asset_id: str,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_LIMIT, description="Maximum timeline events to return.")
    ] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[
        Optional[str], Query(description="Signed cursor returned by a prior history page.")
    ] = None,
    principal: Principal = Depends(get_principal),
    service: AssetHistoryService = Depends(_service),
) -> AssetHistoryPage:
    """Return one authenticated asset-history page in stable chronological order."""
    page = service.list(principal, asset_id, limit=limit, cursor=cursor)
    return AssetHistoryPage(
        items=[
            AssetHistoryEvent(
                event_id=item.event_id,
                event_kind=item.event_kind,
                occurred_at=item.occurred_at,
                actor_id=item.actor_id,
                details=item.details,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )
