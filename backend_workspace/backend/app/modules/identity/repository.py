"""User persistence for the identity module."""

from __future__ import annotations

import uuid
from typing import Dict, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.identity.models import User


class UserRepository:
    """Data access for ``users``; never commits."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: uuid.UUID) -> Optional[User]:
        """Fetch a user by primary key."""
        return self._session.get(User, user_id)

    def get_by_username(self, username: str) -> Optional[User]:
        """Fetch a user by case-insensitive username."""
        return self._session.execute(
            select(User).where(func.lower(User.username) == username.lower())
        ).scalar_one_or_none()

    def lock_many(self, user_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, User]:
        """Lock the requested user rows in UUID order for a domain mutation."""
        ids = sorted(set(user_ids), key=str)
        if not ids:
            return {}
        rows = self._session.execute(
            select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update()
        ).scalars()
        return {user.id: user for user in rows}

    def add(self, username: str, password_hash: str, role: str) -> User:
        """Insert a user and flush so the generated ID is available."""
        user = User(username=username, password_hash=password_hash, role=role)
        self._session.add(user)
        self._session.flush()
        return user
