"""Asset register and event-driven scoring integration tests against PostgreSQL."""

import datetime as dt
import uuid
from decimal import Decimal

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
PREFIX = "asset-itest-"


@pytest.fixture(scope="module")
def db():
    """Yield runtime sessions and clean this module's isolated records with the migration role."""
    base = get_settings()
    if not (base.database_url and base.migration_database_url):
        pytest.skip("database URLs are not configured")
    runtime = create_engine(base.database_url)
    migration = create_engine(base.migration_database_url)
    try:
        with migration.connect() as conn:
            conn.execute(text("SELECT 1 FROM assets LIMIT 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("workspace database is not reachable or not migrated")
    yield sessionmaker(bind=runtime, expire_on_commit=False), migration
    with migration.begin() as conn:
        conn.execute(text("DELETE FROM outbox_events WHERE aggregate_id LIKE :p"), {"p": PREFIX + "%"})
        conn.execute(
            text("DELETE FROM analytics_events WHERE properties->>'asset_id' LIKE :p"),
            {"p": PREFIX + "%"},
        )
        conn.execute(
            text("DELETE FROM audit_logs WHERE entity_id LIKE :p"),
            {"p": PREFIX + "%"},
        )
        conn.execute(text("DELETE FROM alerts WHERE asset_id LIKE :p"), {"p": PREFIX + "%"})
        conn.execute(
            text("DELETE FROM health_score_history WHERE asset_id LIKE :p"), {"p": PREFIX + "%"}
        )
        conn.execute(text("DELETE FROM assets WHERE asset_id LIKE :p"), {"p": PREFIX + "%"})
        conn.execute(
            text(
                "DELETE FROM audit_logs WHERE actor_id IN "
                "(SELECT id FROM users WHERE username LIKE :p)"
            ),
            {"p": PREFIX + "%"},
        )
        conn.execute(text("DELETE FROM users WHERE username LIKE :p"), {"p": PREFIX + "%"})
    runtime.dispose()
    migration.dispose()


def _settings() -> Settings:
    base = get_settings()
    return Settings(**{**base.__dict__, "auth_token_secret": "a" * 40})


def _client(factory) -> TestClient:
    return TestClient(create_app(_settings(), db_probe=lambda: True, session_factory=factory))


def _token(factory, role: str) -> str:
    username = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    with factory() as session:
        UserRepository(session).add(username, hash_password(PASSWORD), role)
        session.commit()
    response = _client(factory).post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["accessToken"]


def _asset_payload(asset_id: str) -> dict:
    today = dt.date.today()
    return {
        "assetId": asset_id,
        "assetType": "Pump",
        "location": "North Yard",
        "installationDate": (today - dt.timedelta(days=365 * 30)).isoformat(),
        "manufacturer": "Acme",
        "lastServiceDate": (today - dt.timedelta(days=365 * 3)).isoformat(),
    }


def test_asset_crud_triggers_scoring_audit_and_analytics(db):
    factory, migration = db
    client = _client(factory)
    headers = {"Authorization": f"Bearer {_token(factory, ROLE_ASSET_MANAGER)}"}
    asset_id = f"{PREFIX}{uuid.uuid4().hex[:12]}"

    created = client.post("/api/v1/assets", json=_asset_payload(asset_id), headers=headers)
    assert created.status_code == 201
    assert created.headers["etag"] == '"v1"'
    assert created.headers["cache-control"] == "private, no-store"
    assert Decimal(created.json()["currentHealthScore"]) == Decimal("50.00")
    assert created.json()["currentColorBand"] == "Amber"

    updated = client.put(
        f"/api/v1/assets/{asset_id}",
        json={"location": "South Yard"},
        headers={**headers, "If-Match": created.headers["etag"]},
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == '"v2"'
    assert updated.json()["location"] == "South Yard"

    serviced = client.put(
        f"/api/v1/assets/{asset_id}",
        json={"lastServiceDate": dt.date.today().isoformat()},
        headers={**headers, "If-Match": updated.headers["etag"]},
    )
    assert serviced.status_code == 200
    assert Decimal(serviced.json()["currentHealthScore"]) == Decimal("80.00")
    assert serviced.json()["currentColorBand"] == "Green"

    deactivated = client.post(
        f"/api/v1/assets/{asset_id}/deactivate",
        headers={**headers, "If-Match": serviced.headers["etag"]},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "deactivated"
    assert deactivated.headers["etag"] == '"v4"'
    active_assets = client.get("/api/v1/assets", headers=headers).json()["items"]
    assert asset_id not in {asset["assetId"] for asset in active_assets}
    assert client.get(f"/api/v1/assets/{asset_id}", headers=headers).status_code == 200

    with migration.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT trigger_type FROM health_score_history "
                "WHERE asset_id = :asset_id ORDER BY calculated_at, id"
            ),
            {"asset_id": asset_id},
        ).scalars().all()
        events = conn.execute(
            text(
                "SELECT event_name FROM analytics_events "
                "WHERE properties->>'asset_id' = :asset_id ORDER BY occurred_at, id"
            ),
            {"asset_id": asset_id},
        ).scalars().all()
    assert triggers == ["asset_create", "asset_update", "service_update"]
    assert sorted(events) == sorted([
        "health_score_recalculated",
        "asset_created",
        "health_score_recalculated",
        "asset_updated",
        "health_score_recalculated",
        "asset_updated",
        "asset_deactivated",
    ])


def test_asset_duplicate_rbac_and_stale_etag_are_enforced(db):
    factory, _ = db
    manager_headers = {"Authorization": f"Bearer {_token(factory, ROLE_ASSET_MANAGER)}"}
    crew_headers = {"Authorization": f"Bearer {_token(factory, ROLE_MAINTENANCE_CREW)}"}
    asset_id = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    client = _client(factory)

    created = client.post("/api/v1/assets", json=_asset_payload(asset_id), headers=manager_headers)
    assert created.status_code == 201
    duplicate = client.post(
        "/api/v1/assets", json=_asset_payload(asset_id), headers=manager_headers
    )
    assert duplicate.status_code == 409
    assert client.post(
        "/api/v1/assets", json=_asset_payload(f"{asset_id}-crew"), headers=crew_headers
    ).status_code == 403
    assert client.put(
        f"/api/v1/assets/{asset_id}",
        json={"location": "West Yard"},
        headers={**manager_headers, "If-Match": '"v99"'},
    ).status_code == 412
    assert client.put(
        f"/api/v1/assets/{asset_id}", json={"location": "West Yard"}, headers=manager_headers
    ).status_code == 428
