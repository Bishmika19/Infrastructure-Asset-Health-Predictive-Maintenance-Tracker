"""Shared FastAPI dependencies: settings, session factory, principal, role guard (DEC-04)."""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import Forbidden, ServiceUnavailable, Unauthenticated
from app.core.logging import actor_id_var
from app.db.session import get_session_factory
from app.modules.identity.service import AuthService
from app.shared.principal import Principal

_bearer_scheme = HTTPBearer(
    auto_error=False, description="Signed bearer token from POST /api/v1/auth/login."
)


# PUBLIC_INTERFACE
def get_request_settings(request: Request) -> Settings:
    """Return the settings snapshot stored on the application by ``create_app``."""
    return request.app.state.settings


# PUBLIC_INTERFACE
def get_session_factory_dep(request: Request) -> sessionmaker[Session]:
    """Return the session factory (an override on ``app.state`` wins, for tests).

    Raises:
        ServiceUnavailable: the database is not configured (503).
    """
    factory = getattr(request.app.state, "session_factory", None)
    if factory is not None:
        return factory
    try:
        return get_session_factory()
    except RuntimeError:
        raise ServiceUnavailable("Database is not configured") from None


# PUBLIC_INTERFACE
def get_auth_service(
    settings: Settings = Depends(get_request_settings),
    factory: sessionmaker[Session] = Depends(get_session_factory_dep),
) -> AuthService:
    """Build the authentication service for the current request."""
    return AuthService(settings, factory)


# PUBLIC_INTERFACE
async def get_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    service: AuthService = Depends(get_auth_service),
) -> Principal:
    """Authenticate the request from its bearer token (401 when missing or invalid).

    Also records the actor ID for structured logs of the remainder of the request.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise Unauthenticated()
    principal = await run_in_threadpool(service.authenticate, credentials.credentials)
    actor_id_var.set(str(principal.user_id))
    return principal


# PUBLIC_INTERFACE
def require_role(*roles: str) -> Callable[[Principal], Principal]:
    """Return a dependency that authenticates and allows only the given roles (403 otherwise).

    Object-level decisions (for example the current-assignee check) belong to each
    module's ``policy.py`` and run against the locked row inside the service.
    """
    allowed = frozenset(roles)

    def guard(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise Forbidden("Your role does not permit this action")
        return principal

    return guard


# PUBLIC_INTERFACE
def set_no_store(response: Response) -> None:
    """Mark API responses ``Cache-Control: private, no-store`` (Case contract)."""
    response.headers["Cache-Control"] = "private, no-store"
