"""Identity routes: ``POST /api/v1/auth/login`` and ``GET /api/v1/auth/me``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings
from app.modules.identity.schemas import LoginRequest, TokenResponse, UserOut
from app.modules.identity.service import AuthService
from app.shared.deps import get_auth_service, get_principal, get_request_settings
from app.shared.principal import Principal

router = APIRouter(prefix="/auth", tags=["identity"])

_PROBLEM_RESPONSES = {
    400: {"description": "Malformed JSON or unknown field."},
    401: {"description": "Invalid credentials or token."},
    422: {"description": "Invalid field values."},
    429: {"description": "Too many failed attempts; see Retry-After."},
}


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in",
    description=(
        "Exchange a username and password for a short-lived signed bearer token. "
        "Every attempt is audited; repeated failures per username or client IP are throttled (429)."
    ),
    operation_id="auth_login",
    responses=_PROBLEM_RESPONSES,
)
def login(
    body: LoginRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_request_settings),
) -> TokenResponse:
    """Authenticate with username and password.

    Parameters:
        body: ``username`` and ``password``.

    Returns:
        ``accessToken`` (send as ``Authorization: Bearer <token>``), ``tokenType``,
        ``expiresIn`` seconds and the authenticated ``user``.
    """
    client_ip = request.client.host if request.client else None
    result = service.login(body.username, body.password, client_ip)
    assert result.user is not None and result.token is not None
    return TokenResponse(
        access_token=result.token,
        token_type="Bearer",
        expires_in=settings.auth_token_ttl_s,
        user=UserOut.model_validate(result.user),
    )


@router.get(
    "/me",
    response_model=UserOut,
    summary="Current user",
    description="Return the authenticated user; also lets a client validate a stored token.",
    operation_id="auth_me",
    responses={401: {"description": "Missing, invalid or expired token."}},
)
def me(principal: Principal = Depends(get_principal)) -> UserOut:
    """Return the authenticated user's ID, username and role."""
    return UserOut(id=principal.user_id, username=principal.username, role=principal.role)
