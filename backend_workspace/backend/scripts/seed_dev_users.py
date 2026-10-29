"""Development-only seeding of one Asset Manager and one Maintenance Crew user (OD-07).

Never run in production. Passwords come from ``SEED_MANAGER_PASSWORD`` and
``SEED_CREW_PASSWORD``; when unset a random password is generated and printed once.
Usernames default to ``manager`` and ``crew`` (``SEED_MANAGER_USERNAME`` /
``SEED_CREW_USERNAME``). Existing usernames are left untouched, so the script is
safe to re-run. Run from the backend root: ``python -m scripts.seed_dev_users``.
"""

from __future__ import annotations

import os
import secrets
import sys
from typing import List, Tuple

from app.core.security import hash_password
from app.db.session import get_session_factory
from app.modules.identity.repository import UserRepository
from app.shared.principal import ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW


def _accounts() -> List[Tuple[str, str, str, bool]]:
    """Return (username, password, role, password_was_generated) for each seed account."""
    accounts = []
    for role, user_env, pass_env, default_user in (
        (ROLE_ASSET_MANAGER, "SEED_MANAGER_USERNAME", "SEED_MANAGER_PASSWORD", "manager"),
        (ROLE_MAINTENANCE_CREW, "SEED_CREW_USERNAME", "SEED_CREW_PASSWORD", "crew"),
    ):
        password = os.getenv(pass_env)
        accounts.append(
            (os.getenv(user_env, default_user), password or secrets.token_urlsafe(12), role, not password)
        )
    return accounts


# PUBLIC_INTERFACE
def seed_dev_users() -> int:
    """Create the development users that do not exist yet; returns the number created."""
    created = 0
    with get_session_factory()() as session:
        repo = UserRepository(session)
        for username, password, role, generated in _accounts():
            if repo.get_by_username(username) is not None:
                print(f"exists:  {username}")
                continue
            repo.add(username, hash_password(password), role)
            created += 1
            shown = f" password={password}" if generated else ""
            print(f"created: {username} role={role}{shown}")
        session.commit()
    return created


if __name__ == "__main__":
    try:
        seed_dev_users()
    except RuntimeError as error:  # e.g. DATABASE_URL not configured
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
