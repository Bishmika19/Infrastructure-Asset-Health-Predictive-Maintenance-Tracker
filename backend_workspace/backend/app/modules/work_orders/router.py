"""Case API routes backed by the single work-order aggregate (DEC-13)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Response, status as http_status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.modules.work_orders.schemas import Case, CasePage, CasePriority, CaseStatus, CreateCase, UpdateCase
from app.modules.work_orders.service import WorkOrderService
from app.shared.concurrency import format_etag, if_match_version
from app.shared.deps import get_principal, get_request_settings, get_session_factory_dep, require_role
from app.shared.idempotency import StoredResponse, idempotency_key
from app.shared.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.shared.principal import ROLE_ASSET_MANAGER, Principal

router = APIRouter(prefix="/cases", tags=["cases"])

_PROBLEM_RESPONSES = {
    400: {"description": "Malformed JSON, unknown field/filter, or invalid conditional header."},
    401: {"description": "Missing, expired, or invalid bearer token."},
    403: {"description": "The authenticated role or assignee is not allowed to mutate this Case."},
    404: {"description": "The asset or Case does not exist."},
    409: {"description": "The asset/alert state, lifecycle command, or idempotency key conflicts."},
    412: {"description": "The supplied ETag is stale."},
    422: {"description": "A known field value or signed cursor is invalid."},
    428: {"description": "PATCH requires a strong If-Match ETag."},
}


def _service(
    settings: Settings = Depends(get_request_settings),
    factory: sessionmaker[Session] = Depends(get_session_factory_dep),
) -> WorkOrderService:
    """Build the request-scoped Case application service."""
    return WorkOrderService(settings, factory)


@router.post(
    "",
    response_model=Case,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create a Case",
    description="Create an Open Case from an active flagged asset using an Idempotency-Key.",
    operation_id="create_case",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
def create_case(
    body: CreateCase,
    response: Response,
    key: str = Depends(idempotency_key),
    principal: Principal = Depends(require_role(ROLE_ASSET_MANAGER)),
    service: WorkOrderService = Depends(_service),
) -> Case | JSONResponse:
    """Create a manager-owned Case or replay the exact committed idempotent response."""
    result = service.create(principal, body.model_dump(), key)
    if isinstance(result, StoredResponse):
        return JSONResponse(result.body, status_code=result.status, headers=result.headers)
    response.headers["ETag"] = format_etag(result.version)
    response.headers["Location"] = f"/api/v1/cases/{result.id}"
    return Case.model_validate(result)


@router.get(
    "",
    response_model=CasePage,
    summary="List Cases",
    description="List authenticated users' Cases in descending creation-time keyset order.",
    operation_id="list_cases",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
def list_cases(
    asset_id: Annotated[Optional[str], Query(min_length=1, max_length=128)] = None,
    status: Annotated[Optional[CaseStatus], Query()] = None,
    priority: Annotated[Optional[CasePriority], Query()] = None,
    assignee_id: Annotated[Optional[uuid.UUID], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[Optional[str], Query()] = None,
    _: Principal = Depends(get_principal),
    service: WorkOrderService = Depends(_service),
) -> CasePage:
    """Return the authenticated user's filtered Case page."""
    page = service.list(
        asset_id=asset_id,
        status=status,
        priority=priority,
        assignee_id=assignee_id,
        limit=limit,
        cursor=cursor,
    )
    return CasePage(items=[Case.model_validate(item) for item in page.items], next_cursor=page.next_cursor)


@router.get(
    "/{case_id}",
    response_model=Case,
    summary="Fetch a Case",
    description="Fetch one authenticated Case view and its strong ETag.",
    operation_id="get_case",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
def get_case(
    case_id: uuid.UUID,
    response: Response,
    _: Principal = Depends(get_principal),
    service: WorkOrderService = Depends(_service),
) -> Case:
    """Return one Case representation and its current strong version ETag."""
    order = service.fetch(case_id)
    response.headers["ETag"] = format_etag(order.version)
    return Case.model_validate(order)


@router.patch(
    "/{case_id}",
    response_model=Case,
    summary="Update a Case",
    description="Apply a sparse authorized Case update using a strong If-Match ETag.",
    operation_id="update_case",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
def update_case(
    case_id: uuid.UUID,
    body: UpdateCase,
    response: Response,
    expected_version: int = Depends(if_match_version),
    principal: Principal = Depends(get_principal),
    service: WorkOrderService = Depends(_service),
) -> Case:
    """Apply an authorized forward lifecycle or permitted metadata update."""
    order = service.update(
        principal, case_id, expected_version, body.model_dump(exclude_unset=True)
    )
    response.headers["ETag"] = format_etag(order.version)
    return Case.model_validate(order)
