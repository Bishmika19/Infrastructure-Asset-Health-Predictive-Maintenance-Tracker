"""Development-only disk adapter for :mod:`app.infrastructure.storage`.

This adapter is intentionally not a production storage implementation: local
disks are neither shared between replicas nor guaranteed to be encrypted.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import BinaryIO

from app.infrastructure.storage.base import InvalidPhoto, PhotoStorageError, StagedPhoto

_CHUNK_SIZE = 64 * 1024
_JPEG_HEADER = b"\xff\xd8\xff"
_PNG_HEADER = b"\x89PNG\r\n\x1a\n"
_MEDIA_DETAILS = {
    "image/jpeg": ("jpg", _JPEG_HEADER),
    "image/png": ("png", _PNG_HEADER),
}


class LocalPhotoStorage:
    """Store staged inspection photos below one development-only filesystem root."""

    def __init__(self, root: Path) -> None:
        """Create a storage adapter rooted at ``root`` without reading configuration."""
        self._root = root

    # PUBLIC_INTERFACE
    def stage(self, source: BinaryIO, max_bytes: int) -> StagedPhoto:
        """Stream a JPEG or PNG to a private staging path and return its verified metadata.

        Raises:
            InvalidPhoto: the stream is empty, is not JPEG/PNG, or exceeds ``max_bytes``.
            PhotoStorageError: a filesystem operation prevents staging.
        """
        header = source.read(len(_PNG_HEADER))
        content_type, extension = self._detect_content_type(header)
        source.seek(0)
        token = uuid.uuid4().hex
        stage_key = f"staging/{token}"
        storage_key = f"photos/{token}.{extension}"
        stage_path = self._path_for(stage_key)
        stage_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        checksum = hashlib.sha256()
        size_bytes = 0
        try:
            with stage_path.open("xb") as destination:
                while chunk := source.read(_CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise InvalidPhoto(f"Photo exceeds the {max_bytes}-byte limit")
                    checksum.update(chunk)
                    destination.write(chunk)
            if size_bytes == 0:
                raise InvalidPhoto("Photo is empty")
            photo = StagedPhoto(
                stage_key=stage_key,
                storage_key=storage_key,
                content_type=content_type,
                size_bytes=size_bytes,
                checksum=checksum.hexdigest(),
            )
            self.verify(photo)
            return photo
        except InvalidPhoto:
            stage_path.unlink(missing_ok=True)
            raise
        except OSError as error:
            stage_path.unlink(missing_ok=True)
            raise PhotoStorageError("Unable to stage inspection photo") from error

    # PUBLIC_INTERFACE
    def verify(self, photo: StagedPhoto) -> None:
        """Check that the staged file still has the recorded type, size, and checksum."""
        path = self._path_for(photo.stage_key)
        try:
            checksum = hashlib.sha256()
            size_bytes = 0
            with path.open("rb") as source:
                header = source.read(len(_PNG_HEADER))
                content_type, _ = self._detect_content_type(header)
                checksum.update(header)
                size_bytes = len(header)
                while chunk := source.read(_CHUNK_SIZE):
                    checksum.update(chunk)
                    size_bytes += len(chunk)
        except OSError as error:
            raise PhotoStorageError("Staged inspection photo is unavailable") from error
        if (
            content_type != photo.content_type
            or size_bytes != photo.size_bytes
            or checksum.hexdigest() != photo.checksum
        ):
            raise PhotoStorageError("Staged inspection photo verification failed")

    # PUBLIC_INTERFACE
    def promote(self, photo: StagedPhoto) -> None:
        """Atomically move one verified staged image to its final storage key."""
        self.verify(photo)
        source = self._path_for(photo.stage_key)
        destination = self._path_for(photo.storage_key)
        try:
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.replace(source, destination)
        except OSError as error:
            raise PhotoStorageError("Unable to promote inspection photo") from error

    # PUBLIC_INTERFACE
    def delete(self, photo: StagedPhoto) -> None:
        """Best-effort removal of either stage or final local files for ``photo``."""
        for key in (photo.stage_key, photo.storage_key):
            try:
                self._path_for(key).unlink(missing_ok=True)
            except OSError:
                # Cleanup must never conceal the service error that caused it.
                pass

    # PUBLIC_INTERFACE
    def sweep_staged(self, older_than: int) -> int:
        """Delete abandoned staged files older than ``older_than`` seconds.

        Only the private ``staging`` subtree is examined. Any filesystem race or
        unreadable entry is ignored so a best-effort cleanup never interrupts
        scoring or delivery work.
        """
        cutoff = time.time() - max(0, older_than)
        staging_root = self._root / "staging"
        removed = 0
        try:
            candidates = list(staging_root.rglob("*"))
        except OSError:
            return 0
        for candidate in candidates:
            try:
                if candidate.is_file() and candidate.stat().st_mtime <= cutoff:
                    candidate.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    @staticmethod
    def _detect_content_type(header: bytes) -> tuple[str, str]:
        """Return the byte-sniffed media type and filename extension for one image."""
        for content_type, (extension, signature) in _MEDIA_DETAILS.items():
            if header.startswith(signature):
                return content_type, extension
        raise InvalidPhoto("Photo must be a JPEG or PNG image")

    def _path_for(self, storage_key: str) -> Path:
        """Resolve a trusted adapter-generated relative key under the configured root."""
        return self._root / storage_key
