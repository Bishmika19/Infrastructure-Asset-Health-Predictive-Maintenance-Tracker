"""Inspection/photo integration tests against the workspace PostgreSQL database."""

import datetime as dt
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.main import create_app
from app.modules.identity.repository import UserRepository
from app.shared.principal import ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW

PASSWORD = "Test-Passw0rd!"
PREFIX = "inspection-itest-"


@pytest.fixture(scope="module")
def db():
    """Yield database handles and remove this module's isolated data as the migration role."""
    base = get_settings()
    if not (base.database_url and base.migration_database_url):
        pytest.skip("database URLs are not configured")
    runtime = create_engine(base.database_url)
    migration = create_engine(base.migration_database_url)
    try:
        with migration.connect() as connection:
            connection.execute(text("SELECT 1 FROM inspection_photos LIMIT 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("workspace database is not reachable or not migrated")

    yield sessionmaker(bind=runtime, expire_on_commit=False), migration

    with migration.begin() as connection:
        connection.execute(
            text("DELETE FROM analytics_events WHERE properties->>'asset_id' LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text(
                "DELETE FROM audit_logs WHERE entity_id IN "
                "(SELECT id::text FROM inspections WHERE asset_id LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM alerts WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM health_score_history WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text(
                "DELETE FROM inspection_photos WHERE inspection_id IN "
                "(SELECT id FROM inspections WHERE asset_id LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM inspections WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM assets WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text(
                "DELETE FROM audit_logs WHERE actor_id IN "
                "(SELECT id FROM users WHERE username LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM users WHERE username LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
    runtime.dispose()
    migration.dispose()


def _settings(photo_root: Path) -> Settings:
    """Return deterministic API settings with an isolated local storage directory."""
    base = get_settings()
    return Settings(
        **{
            **base.__dict__,
            "auth_token_secret": "a" * 40,
            "photo_storage_root": photo_root,
        }
    )


def _client(factory, photo_root: Path) -> TestClient:
    """Build a client wired to the supplied runtime database and storage root."""
    return TestClient(create_app(_settings(photo_root), db_probe=lambda: True, session_factory=factory))


def _token(factory, role: str) -> str:
    """Create one active user and return an authenticated bearer token."""
    username = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    with factory() as session:
        UserRepository(session).add(username, hash_password(PASSWORD), role)
        session.commit()
    response = _client(factory, Path("/tmp")).post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["accessToken"]


def _asset_payload(asset_id: str) -> dict:
    """Create scoring inputs that a Critical inspection will move below the alert threshold."""
    today = dt.date.today()
    return {
        "assetId": asset_id,
        "assetType": "Pump",
        "location": "North Yard",
        "installationDate": (today - dt.timedelta(days=365 * 30)).isoformat(),
        "manufacturer": "Acme",
        "lastServiceDate": (today - dt.timedelta(days=365 * 3)).isoformat(),
    }


def _jpeg_bytes() -> bytes:
    """Return an upload payload detected as JPEG from bytes rather than client headers."""
    return b"\xff\xd8\xff\xe0JFIF\x00" + (b"inspection-image" * 20)


def test_crew_logs_verified_photo_and_atomic_score_side_effects(db, tmp_path):
    """Crew logging persists metadata, scoring, alert, audit, and analytics together."""
    factory, migration = db
    client = _client(factory, tmp_path)
    manager_headers = {"Authorization": f"Bearer {_token(factory, ROLE_ASSET_MANAGER)}"}
    crew_headers = {"Authorization": f"Bearer {_token(factory, ROLE_MAINTENANCE_CREW)}"}
    asset_id = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    created = client.post("/api/v1/assets", json=_asset_payload(asset_id), headers=manager_headers)
    assert created.status_code == 201

    response = client.post(
        f"/api/v1/assets/{asset_id}/inspections",
        data={"condition_rating": "Critical", "observations": "Pump vibration is severe."},
        files={"photos": ("claimed.txt", _jpeg_bytes(), "text/plain")},
        headers=crew_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["conditionRating"] == "Critical"
    assert body["photos"][0]["contentType"] == "image/jpeg"
    assert body["photos"][0]["sizeBytes"] == len(_jpeg_bytes())
    assert response.headers["cache-control"] == "private, no-store"
    history = client.get(f"/api/v1/assets/{asset_id}/inspections", headers=manager_headers)
    assert history.status_code == 200
    forbidden = client.post(
        f"/api/v1/assets/{asset_id}/inspections",
        data={"condition_rating": "Good", "observations": "Not permitted."},
        files={"photos": ("valid.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=manager_headers,
    )
    assert forbidden.status_code == 403

    with migration.connect() as connection:
        trigger = connection.execute(
            text(
                "SELECT trigger_type FROM health_score_history WHERE asset_id = :asset_id "
                "ORDER BY calculated_at DESC, id DESC LIMIT 1"
            ),
            {"asset_id": asset_id},
        ).scalar_one()
        photo_count = connection.execute(
            text("SELECT count(*) FROM inspection_photos WHERE inspection_id = :inspection_id"),
            {"inspection_id": body["id"]},
        ).scalar_one()
        audit_count = connection.execute(
            text(
                "SELECT count(*) FROM audit_logs WHERE entity_type = 'inspection' "
                "AND entity_id = :inspection_id"
            ),
            {"inspection_id": body["id"]},
        ).scalar_one()
        event = connection.execute(
            text(
                "SELECT properties->>'photo_count' FROM analytics_events "
                "WHERE event_name = 'inspection_logged' AND properties->>'asset_id' = :asset_id"
            ),
            {"asset_id": asset_id},
        ).scalar_one()

    assert trigger == "inspection"
    assert photo_count == audit_count == 1
    assert event == "1"
    assert len(list((tmp_path / "photos").glob("*"))) == 1


def test_invalid_photo_is_rejected_before_metadata_is_committed(db, tmp_path):
    """Invalid byte signatures yield a 422 and leave no inspection or photo rows behind."""
    factory, migration = db
    client = _client(factory, tmp_path)
    headers = {"Authorization": f"Bearer {_token(factory, ROLE_MAINTENANCE_CREW)}"}
    manager_headers = {"Authorization": f"Bearer {_token(factory, ROLE_ASSET_MANAGER)}"}
    asset_id = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    created = client.post("/api/v1/assets", json=_asset_payload(asset_id), headers=manager_headers)
    assert created.status_code == 201

    rejected = client.post(
        f"/api/v1/assets/{asset_id}/inspections",
        data={"condition_rating": "Good", "observations": "No metadata should persist."},
        files={"photos": ("fake.png", b"not an image", "image/png")},
        headers=headers,
    )
    assert rejected.status_code == 422

    with migration.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM inspections WHERE asset_id = :asset_id"),
            {"asset_id": asset_id},
        ).scalar_one()
    assert count == 0
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
