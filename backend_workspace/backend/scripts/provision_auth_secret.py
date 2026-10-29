"""Create the persistent AUTH_TOKEN_SECRET file without ever printing the secret.

The secret is written to a protected file outside the workspace and outside git
(default ``~/.local/share/asset-health-backend/auth_token_secret``, mode 0600), which
``app/core/config.py`` reads when the ``AUTH_TOKEN_SECRET`` environment variable is unset.
The script is idempotent: an existing valid secret is kept unless ``--rotate`` is passed
(rotation invalidates every issued bearer token).

Usage: ``python -m scripts.provision_auth_secret [--rotate]``
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from typing import List, Optional

from app.core.config import DEFAULT_AUTH_SECRET_FILE, MIN_TOKEN_SECRET_LENGTH


# PUBLIC_INTERFACE
def provision(path: Path, rotate: bool = False) -> str:
    """Ensure ``path`` holds a long-enough secret; return 'created', 'kept' or 'rotated'."""
    if path.is_file() and not rotate:
        if len(path.read_text(encoding="utf-8").strip()) >= MIN_TOKEN_SECRET_LENGTH:
            os.chmod(path, 0o600)
            return "kept"
    outcome = "rotated" if path.is_file() else "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create the temp file with mode 0600 from the start so the secret is never world-readable.
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(secrets.token_urlsafe(48) + "\n")
    os.replace(tmp, path)
    return outcome


# PUBLIC_INTERFACE
def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint; prints only the outcome and the file location, never the secret."""
    parser = argparse.ArgumentParser(description="Provision the persistent AUTH_TOKEN_SECRET file")
    parser.add_argument("--rotate", action="store_true", help="replace the existing secret")
    args = parser.parse_args(argv)
    path = Path(os.getenv("AUTH_TOKEN_SECRET_FILE", str(DEFAULT_AUTH_SECRET_FILE)))
    print(f"auth token secret {provision(path, args.rotate)}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
