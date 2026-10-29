"""Photo-storage adapters.

The local adapter is strictly for development. Production must provide a private,
encrypted, shared implementation of :class:`PhotoStorage`.
"""

from app.infrastructure.storage.base import PhotoStorage, StagedPhoto
from app.infrastructure.storage.local import LocalPhotoStorage

__all__ = ["LocalPhotoStorage", "PhotoStorage", "StagedPhoto"]
