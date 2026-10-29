"""Case API schemas; Cases are the transport alias for work orders."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal, Optional

from pydantic import Field, model_validator

from app.shared.schema_base import ApiModel, ApiResponseModel

CaseStatus = Literal["Open", "Assigned", "In Progress", "Complete"]
CasePriority = Literal["Low", "Medium", "High", "Critical"]
AssetType = Literal["Transformer", "Substation", "Pump", "Pipeline", "Other"]


class CreateCase(ApiModel):
    """Validated request body for a manager-created Case."""

    asset_id: str = Field(..., min_length=1, max_length=128, description="Flagged active asset ID.")
    fault_description: str = Field(
        ..., min_length=1, max_length=4000, description="Nonblank maintenance fault description."
    )
    priority: CasePriority = Field(..., description="Maintenance priority.")
    assignee_id: Optional[uuid.UUID] = Field(None, description="Optional active crew assignee.")
    alert_id: Optional[uuid.UUID] = Field(None, description="Optional current flag episode identifier.")


class UpdateCase(ApiModel):
    """Sparse mutable Case fields; explicit null may clear an Open Case assignee."""

    fault_description: Optional[str] = Field(None, min_length=1, max_length=4000)
    priority: Optional[CasePriority] = Field(None)
    assignee_id: Optional[uuid.UUID] = Field(None)
    status: Optional[CaseStatus] = Field(None)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateCase":
        """Reject an empty Case PATCH before it enters a transaction."""
        if not self.model_fields_set:
            raise ValueError("At least one Case field must be supplied")
        return self


class AssetSnapshot(ApiResponseModel):
    """Immutable asset values captured when a Case is created."""

    asset_id: str
    asset_type: AssetType
    location: str
    installation_date: dt.date
    manufacturer: str
    last_service_date: Optional[dt.date]


class Case(ApiResponseModel):
    """Full Case representation returned by create, update, fetch, and list."""

    id: uuid.UUID
    asset_id: str
    asset_snapshot: AssetSnapshot
    alert_id: Optional[uuid.UUID]
    fault_description: str
    priority: CasePriority
    assignee_id: Optional[uuid.UUID]
    status: CaseStatus
    created_by: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime
    version: int


class CasePage(ApiResponseModel):
    """Descending creation-time keyset page of Cases."""

    items: list[Case] = Field(..., description="Cases ordered by createdAt then ID descending.")
    next_cursor: Optional[str] = Field(None, description="Signed continuation cursor.")
