"""Photo-storage protocol for staged inspection images (DEC-05).

Objects are staged and checksum-verified before database work begins. Metadata
uses the deterministic final ``storage_key`` returned by :meth:`stage`; promotion
only occurs after the database transaction commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol


class PhotoStorageError(Exception):
    """Base error raised by a photo-storage adapter."""


class InvalidPhoto(PhotoStorageError):
    """The supplied stream is not a permitted inspection image."""


@dataclass(frozen=True)
class StagedPhoto:
    """Verified photo metadata and the storage locations used during promotion."""

    stage_key: str
    storage_key: str
    content_type: str
    size_bytes: int
    checksum: str


class PhotoStorage(Protocol):
    """Port implemented by development and production photo-storage adapters."""

    # PUBLIC_INTERFACE
    def stage(self, source: BinaryIO, max_bytes: int) -> StagedPhoto:
        """Stream, detect, hash, and stage one image without publishing it."""

    # PUBLIC_INTERFACE
    def verify(self, photo: StagedPhoto) -> None:
        """Raise when a staged image does not match its recorded checksum or size."""

    # PUBLIC_INTERFACE
    def promote(self, photo: StagedPhoto) -> None:
        """Publish a verified staged image under its final storage key."""

    # PUBLIC_INTERFACE
    def delete(self, photo: StagedPhoto) -> None:
        """Best-effort removal of an unpublished or published image."""

    # PUBLIC_INTERFACE
    def sweep_staged(self, older_than: int) -> int:
        """Delete staged objects older than ``older_than`` seconds and return their count."""
