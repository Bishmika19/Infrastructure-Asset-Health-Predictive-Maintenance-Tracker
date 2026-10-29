"""Authenticated principal and audit actor types (framework-free)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

ROLE_ASSET_MANAGER = "asset_manager"
ROLE_MAINTENANCE_CREW = "maintenance_crew"
ALL_ROLES = (ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW)

ACTOR_USER = "user"
ACTOR_SYSTEM = "system"
ACTOR_ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class Actor:
    """Who performed an audited action: a user, the system (worker), or anonymous."""

    kind: str
    id: Optional[uuid.UUID] = None


# Actor used by the nightly job and other worker-initiated work.
SYSTEM_ACTOR = Actor(kind=ACTOR_SYSTEM)
ANONYMOUS_ACTOR = Actor(kind=ACTOR_ANONYMOUS)


@dataclass(frozen=True)
class Principal:
    """An authenticated, active user resolved from a bearer token."""

    user_id: uuid.UUID
    username: str
    role: str

    @property
    def actor(self) -> Actor:
        """The audit actor for this principal."""
        return Actor(kind=ACTOR_USER, id=self.user_id)

    @property
    def is_asset_manager(self) -> bool:
        """True for the Asset Manager role."""
        return self.role == ROLE_ASSET_MANAGER

    @property
    def is_maintenance_crew(self) -> bool:
        """True for the Maintenance Crew role."""
        return self.role == ROLE_MAINTENANCE_CREW
