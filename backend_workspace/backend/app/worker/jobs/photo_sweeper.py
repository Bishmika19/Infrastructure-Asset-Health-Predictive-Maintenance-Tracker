"""Scheduled cleanup of abandoned staged inspection photos (DEC-05)."""

from __future__ import annotations

from app.infrastructure.storage.base import PhotoStorage


class PhotoSweeper:
    """Delegate staged-object cleanup to the configured storage adapter."""

    def __init__(self, storage: PhotoStorage, staging_ttl_s: int) -> None:
        """Create a sweeper with a non-negative retention duration."""
        self._storage = storage
        self._staging_ttl_s = max(0, staging_ttl_s)

    # PUBLIC_INTERFACE
    def run(self) -> int:
        """Delete staged objects older than the configured retention and return the count."""
        return self._storage.sweep_staged(self._staging_ttl_s)
