"""Development local-photo-storage tests (DEC-05)."""

from io import BytesIO

import pytest

from app.infrastructure.storage.base import InvalidPhoto, PhotoStorageError
from app.infrastructure.storage.local import LocalPhotoStorage


def _jpeg_bytes() -> bytes:
    """Return enough JPEG-prefixed test bytes for byte-sniffing and hashing."""
    return b"\xff\xd8\xff\xe0" + b"JFIF\x00" + (b"image-data" * 20)


def test_local_storage_stages_verifies_promotes_and_deletes(tmp_path):
    """A verified stage gets a final key only after the explicit promotion call."""
    storage = LocalPhotoStorage(tmp_path)
    photo = storage.stage(BytesIO(_jpeg_bytes()), max_bytes=10_000_000)

    assert photo.content_type == "image/jpeg"
    assert photo.size_bytes == len(_jpeg_bytes())
    assert (tmp_path / photo.stage_key).is_file()
    storage.verify(photo)

    storage.promote(photo)
    assert not (tmp_path / photo.stage_key).exists()
    assert (tmp_path / photo.storage_key).is_file()

    storage.delete(photo)
    assert not (tmp_path / photo.storage_key).exists()


def test_local_storage_rejects_invalid_or_oversized_images_without_leaving_files(tmp_path):
    """Non-image and oversized streams fail before any usable staged file remains."""
    storage = LocalPhotoStorage(tmp_path)
    with pytest.raises(InvalidPhoto):
        storage.stage(BytesIO(b"not an image"), max_bytes=100)
    with pytest.raises(InvalidPhoto):
        storage.stage(BytesIO(_jpeg_bytes()), max_bytes=10)

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_local_storage_detects_tampering_during_verification(tmp_path):
    """A staged object modified after hashing cannot be promoted."""
    storage = LocalPhotoStorage(tmp_path)
    photo = storage.stage(BytesIO(_jpeg_bytes()), max_bytes=10_000_000)
    (tmp_path / photo.stage_key).write_bytes(b"\x89PNG\r\n\x1a\nreplaced")

    with pytest.raises(PhotoStorageError):
        storage.verify(photo)
