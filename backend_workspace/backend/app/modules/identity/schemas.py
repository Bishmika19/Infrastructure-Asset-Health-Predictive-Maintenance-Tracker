"""Identity request and response schemas."""

from __future__ import annotations

import uuid

from pydantic import Field

from app.shared.schema_base import ApiModel, ApiResponseModel


class LoginRequest(ApiModel):
    """Credentials for ``POST /api/v1/auth/login``."""

    username: str = Field(..., min_length=1, max_length=128, description="Account username.")
    password: str = Field(..., min_length=1, max_length=256, description="Account password.")


class UserOut(ApiResponseModel):
    """The authenticated user as exposed to clients (no credential material)."""

    id: uuid.UUID = Field(..., description="User ID.")
    username: str = Field(..., description="Username.")
    role: str = Field(..., description="'asset_manager' or 'maintenance_crew'.")


class TokenResponse(ApiResponseModel):
    """A signed bearer token and the authenticated user."""

    access_token: str = Field(..., description="Signed bearer token for the Authorization header.")
    token_type: str = Field("Bearer", description="Always 'Bearer'.")
    expires_in: int = Field(..., description="Token lifetime in seconds.")
    user: UserOut
