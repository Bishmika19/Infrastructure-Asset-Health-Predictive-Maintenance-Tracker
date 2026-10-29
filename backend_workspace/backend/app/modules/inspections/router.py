"""Inspection-history and crew inspection-upload routes (FR-3, DEC-05)."""

from __future__ import annotations

from typing import Annotated, Optional, Sequence

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import ServiceUnavailable, ValidationFailed
from app.infrastructure.storage.base import InvalidPhoto, PhotoStorageError, StagedPhoto
from app.infrastructure.storage.local import LocalPhotoStorage
from app.modules.inspections.schemas import (
    ConditionRating,
    InspectionOut,
    InspectionPage,
    InspectionPhotoOut,
    MAX_PHOTO_BYTES,
    MAX_PHOTOS_PER_INSPECTION,
)
from app.modules.inspections.service import InspectionService, InspectionView
from app.shared.deps import get_principal, get_request_settings, get_session_factory_dep, require_role
from app.shared.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.shared.principal import ROLE_MAINTENANCE_CREW, Principal

router = APIRouter(prefix="/assets/{asset_id}/inspections", tags=["inspections"])

_PROBLEM_RESPONSES = {
    400: {"description": "Malformed multipart request or unknown query parameter."},
    401: {"description": "Missing, expired, or invalid bearer token."},
    403: {"description": "Maintenance Crew role required to log an inspection."},
    404: {"description": "Asset does not exist."},
    409: {"description": "Asset is deactivated."},
    413: {"description": "Multipart body or one photo exceeds the configured size limit."},
    422: {"description": "Invalid inspection field, photo bytes, or cursor."},
    503: {"description": "Photo storage is unavailable."},
}


def _service(
    settings: Settings = Depends(get_request_settings),
    factory: sessionmaker[Session] = Depends(get_session_factory_dep),
) -> InspectionService:
    """Build the request-scoped inspection application service."""
    return InspectionService(settings, factory)


def _out(view: InspectionView) -> InspectionOut:
    """Map framework-free service output into its documented API representation."""
    inspection = view.inspection
    return InspectionOut(
        id=inspection.id,
        asset_id=inspection.asset_id,
        condition_rating=inspection.condition_rating,
        observations=inspection.observations,
        inspector_id=inspection.inspector_id,
        inspected_at=inspection.inspected_at,
        created_at=inspection.created_at,
        photos=[InspectionPhotoOut.model_validate(photo) for photo in view.photos],
    )


async def _stage_uploads(
    uploads: Sequence[UploadFile], storage: LocalPhotoStorage
) -> list[StagedPhoto]:
    """Stage and verify the uploaded images before entering a database transaction."""
    if len(uploads) > MAX_PHOTOS_PER_INSPECTION:
        raise ValidationFailed(f"At most {MAX_PHOTOS_PER_INSPECTION} photos are allowed")
    staged: list[StagedPhoto] = []
    try:
        for upload in uploads:
            try:
                photo = await run_in_threadpool(storage.stage, upload.file, MAX_PHOTO_BYTES)
            except InvalidPhoto as error:
                raise ValidationFailed(str(error)) from error
            staged.append(photo)
        return staged
    except Exception:
        for photo in staged:
            await run_in_threadpool(storage.delete, photo)
        raise
    finally:
        for upload in uploads:
            await upload.close()


async def _delete_staged(storage: LocalPhotoStorage, photos: Sequence[StagedPhoto]) -> None:
    """Best-effort cleanup when the database transaction cannot retain staged metadata."""
    for photo in photos:
        await run_in_threadpool(storage.delete, photo)


@router.get(
    "",
    response_model=InspectionPage,
    summary="List asset inspections",
    description="List authenticated users' inspection history for one asset, newest first.",
    operation_id="list_asset_inspections",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
def list_asset_inspections(
    asset_id: str,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_LIMIT, description="Maximum inspection records to return.")
    ] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[
        Optional[str], Query(description="Signed cursor returned by a prior inspection page.")
    ] = None,
    _: Principal = Depends(get_principal),
    service: InspectionService = Depends(_service),
) -> InspectionPage:
    """Return inspection history and non-public verified photo metadata for one asset."""
    page = service.list(asset_id, limit=limit, cursor=cursor)
    return InspectionPage(items=[_out(view) for view in page.items], next_cursor=page.next_cursor)


@router.post(
    "",
    response_model=InspectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log an inspection",
    description=(
        "Maintenance Crew log a condition rating and observations with up to ten byte-verified "
        "JPEG or PNG photos. Multipart field name: `photos`."
    ),
    operation_id="create_asset_inspection",
    responses=_PROBLEM_RESPONSES,
)
# PUBLIC_INTERFACE
async def create_asset_inspection(
    asset_id: str,
    condition_rating: Annotated[
        ConditionRating, Form(description="Observed condition rating for the asset.")
    ],
    observations: Annotated[
        str, Form(min_length=1, max_length=4000, description="Crew observations for the inspection.")
    ],
    principal: Principal = Depends(require_role(ROLE_MAINTENANCE_CREW)),
    service: InspectionService = Depends(_service),
    settings: Settings = Depends(get_request_settings),
    photos: list[UploadFile] = File(
        default=[],
        description="Optional JPEG/PNG photos; at most 10 files of 10,000,000 bytes each.",
    ),
) -> InspectionOut:
    """Stage verified photo bytes, atomically persist the inspection, then publish the photos."""
    storage = LocalPhotoStorage(settings.photo_storage_root)
    try:
        staged = await _stage_uploads(photos, storage)
    except PhotoStorageError as error:
        raise ServiceUnavailable("Photo storage is unavailable") from error

    try:
        view = await run_in_threadpool(
            service.create,
            principal,
            asset_id,
            condition_rating=condition_rating,
            observations=observations,
            photos=staged,
        )
    except Exception:
        await _delete_staged(storage, staged)
        raise

    try:
        for photo in staged:
            await run_in_threadpool(storage.promote, photo)
    except PhotoStorageError as error:
        # The committed metadata keeps the stable final key. The future photo sweeper can
        # safely identify this retained staged object and retry/clean it without data loss.
        raise ServiceUnavailable("Photo storage promotion is pending") from error
    return _out(view)
