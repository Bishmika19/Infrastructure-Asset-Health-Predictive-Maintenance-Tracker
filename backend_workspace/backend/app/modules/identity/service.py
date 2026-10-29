"""Authentication service: login with throttling and audit, principal resolution (A-2, A-3, A-19)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import TooManyRequests, Unauthenticated
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    issue_token,
    password_needs_rehash,
    verify_password,
    verify_token,
)
from app.db.unit_of_work import run_in_transaction
from app.modules.audit.repository import AuditRepository
from app.modules.audit.writer import (
    EVENT_LOGIN_FAILED,
    EVENT_LOGIN_SUCCEEDED,
    EVENT_LOGIN_THROTTLED,
    AuditWriter,
)
from app.modules.identity.models import User
from app.modules.identity.repository import UserRepository
from app.shared.principal import ANONYMOUS_ACTOR, Actor, Principal


@dataclass(frozen=True)
class LoginResult:
    """Outcome of a login attempt, computed inside one transaction that always commits."""

    token: Optional[str] = None
    user: Optional[User] = None
    throttled_retry_after_s: Optional[int] = None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AuthService:
    """Login and bearer-token authentication."""

    def __init__(self, settings: Settings, factory: sessionmaker[Session]) -> None:
        self._settings = settings
        self._factory = factory

    # PUBLIC_INTERFACE
    def login(self, username: str, password: str, client_ip: Optional[str]) -> LoginResult:
        """Verify credentials, audit the attempt, and issue a token on success.

        Every attempt is audited and the audit row commits even when the login is
        refused. Failures are counted per username and per client IP from
        ``audit_logs`` inside the throttle window, so the limit is shared by all
        replicas.

        Raises:
            TooManyRequests: the username or client IP exceeded the failure limit (429).
            Unauthenticated: the credentials are wrong or the account is inactive (401).
        """
        result = run_in_transaction(
            self._factory, lambda session: self._attempt(session, username, password, client_ip)
        )
        if result.throttled_retry_after_s is not None:
            raise TooManyRequests("Too many failed login attempts", result.throttled_retry_after_s)
        if result.token is None:
            raise Unauthenticated("Invalid username or password")
        return result

    def _attempt(
        self, session: Session, username: str, password: str, client_ip: Optional[str]
    ) -> LoginResult:
        audit = AuditWriter(session)
        meta = {"clientIp": client_ip} if client_ip else {}
        retry_after = self._throttle_retry_after(session, username, client_ip)
        if retry_after is not None:
            audit.record(
                EVENT_LOGIN_THROTTLED, ANONYMOUS_ACTOR, metadata=meta, attempted_username=username
            )
            return LoginResult(throttled_retry_after_s=retry_after)

        user = UserRepository(session).get_by_username(username)
        # Always run one hash verification so timing does not reveal whether the account exists.
        valid = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
        if user is None or not valid or not user.is_active:
            reason = "unknown_user" if user is None else ("inactive" if valid else "bad_password")
            audit.record(
                EVENT_LOGIN_FAILED,
                ANONYMOUS_ACTOR,
                metadata={**meta, "reason": reason},
                attempted_username=username,
            )
            return LoginResult()

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        audit.record(
            EVENT_LOGIN_SUCCEEDED,
            Actor(kind="user", id=user.id),
            entity_type="user",
            entity_id=str(user.id),
            metadata=meta,
            attempted_username=username,
        )
        token = issue_token(
            self._settings.auth_token_secret,
            str(user.id),
            user.role,
            self._settings.auth_token_ttl_s,
        )
        return LoginResult(token=token, user=user)

    def _throttle_retry_after(
        self, session: Session, username: str, client_ip: Optional[str]
    ) -> Optional[int]:
        """Return seconds until a counted failure leaves the window, or None when allowed."""
        cfg = self._settings
        window = dt.timedelta(seconds=cfg.login_window_s)
        since = _utcnow() - window
        repo = AuditRepository(session)
        checks = [(cfg.login_max_failures_per_username, {"attempted_username": username})]
        if client_ip:
            checks.append((cfg.login_max_failures_per_ip, {"client_ip": client_ip}))
        retry: Optional[int] = None
        for limit, scope in checks:
            if repo.count_events_since(EVENT_LOGIN_FAILED, since, **scope) >= limit:
                oldest = repo.oldest_event_since(EVENT_LOGIN_FAILED, since, **scope)
                wait = int((oldest + window - _utcnow()).total_seconds()) + 1 if oldest else 1
                retry = max(retry or 1, wait)
        return retry

    # PUBLIC_INTERFACE
    def authenticate(self, token: str) -> Principal:
        """Resolve a bearer token to an active principal.

        The signature and expiry are verified, then ``users`` is consulted so that
        deactivated accounts and role changes take effect immediately.

        Raises:
            Unauthenticated: the token is invalid or expired, or the user is gone or inactive.
        """
        claims = verify_token(self._settings.auth_token_secret, token)
        try:
            user_id = uuid.UUID(claims.user_id)
        except ValueError:
            raise Unauthenticated("Invalid token") from None

        def load(session: Session) -> Optional[Principal]:
            user = UserRepository(session).get(user_id)
            if user is None or not user.is_active:
                return None
            return Principal(user_id=user.id, username=user.username, role=user.role)

        principal = run_in_transaction(self._factory, load)
        if principal is None:
            raise Unauthenticated("Invalid token")
        return principal
