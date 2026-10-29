"""Predictive-alert episode and maintenance-queue integration tests."""

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
from app.modules.inspections.models import Inspection
from app.modules.scoring.service import ScoringService
from app.shared.principal import ROLE_ASSET_MANAGER

PASSWORD = "Test-Passw0rd!"
PREFIX = "alert-itest-"


@pytest.fixture(scope="module")
def db():
    """Yield database handles and remove this module's isolated test data."""
    base = get_settings()
    if not (base.database_url and base.migration_database_url):
        pytest.skip("database URLs are not configured")
    runtime = create_engine(base.database_url)
    migration = create_engine(base.migration_database_url)
    try:
        with migration.connect() as connection:
            connection.execute(text("SELECT 1 FROM alerts LIMIT 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("workspace database is not reachable or not migrated")

    yield sessionmaker(bind=runtime, expire_on_commit=False), migration

    with migration.begin() as connection:
        connection.execute(
            text("DELETE FROM outbox_events WHERE aggregate_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM analytics_events WHERE properties->>'asset_id' LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(text("DELETE FROM alerts WHERE asset_id LIKE :prefix"), {"prefix": PREFIX + "%"})
        connection.execute(
            text("DELETE FROM health_score_history WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM inspections WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(text("DELETE FROM assets WHERE asset_id LIKE :prefix"), {"prefix": PREFIX + "%"})
        connection.execute(
            text(
                "DELETE FROM audit_logs WHERE actor_id IN "
                "(SELECT id FROM users WHERE username LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM users WHERE username LIKE :prefix"), {"prefix": PREFIX + "%"}
        )
    runtime.dispose()
    migration.dispose()


def _settings() -> Settings:
    """Return deterministic token settings for TestClient authentication."""
    base = get_settings()
    return Settings(**{**base.__dict__, "auth_token_secret": "a" * 40})


def _client(factory) -> TestClient:
    """Create an API client that uses the supplied runtime session factory."""
    return TestClient(create_app(_settings(), db_probe=lambda: True, session_factory=factory))


def _manager_token(factory) -> tuple[str, uuid.UUID]:
    """Create an active asset manager and return its bearer token and user ID."""
    username = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    with factory() as session:
        user = UserRepository(session).add(username, hash_password(PASSWORD), ROLE_ASSET_MANAGER)
        session.commit()
        user_id = user.id
    response = _client(factory).post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()["accessToken"], user_id


def _asset_payload(asset_id: str, installation_years: int, last_service_date: dt.date) -> dict:
    """Build a valid asset creation payload with controllable scoring inputs."""
    today = dt.date.today()
    return {
        "assetId": asset_id,
        "assetType": "Pump",
        "location": "North Yard",
        "installationDate": (today - dt.timedelta(days=365 * installation_years)).isoformat(),
        "manufacturer": "Acme",
        "lastServiceDate": last_service_date.isoformat(),
    }


def _score_from_inspection(
    factory,
    asset_id: str,
    manager_id: uuid.UUID,
    rating: str,
    at: dt.datetime,
) -> None:
    """Persist an inspection and score it in the same transaction as production services use."""
    with factory() as session:
        inspection = Inspection(
            asset_id=asset_id,
            condition_rating=rating,
            observations=f"{rating} test observation",
            inspector_id=manager_id,
            inspected_at=at,
        )
        session.add(inspection)
        session.flush()
        ScoringService(session).recalculate(
            asset_id,
            "inspection",
            actor=__import__("app.shared.principal", fromlist=["Actor"]).Actor(
                kind="user", id=manager_id
            ),
            inspection_id=inspection.id,
            now=at,
        )
        session.commit()


def test_alert_episode_recovery_reflag_outbox_and_queue_ordering(db):
    """Opening, recovery, and reflagging are durable while the queue uses DEC-09 ordering."""
    factory, migration = db
    client = _client(factory)
    token, manager_id = _manager_token(factory)
    headers = {"Authorization": f"Bearer {token}"}
    low_asset_id = f"{PREFIX}low-{uuid.uuid4().hex[:10]}"
    high_asset_id = f"{PREFIX}high-{uuid.uuid4().hex[:10]}"

    low_created = client.post(
        "/api/v1/assets",
        json=_asset_payload(low_asset_id, installation_years=30, last_service_date=dt.date.today()),
        headers=headers,
    )
    high_created = client.post(
        "/api/v1/assets",
        json=_asset_payload(
            high_asset_id,
            installation_years=12,
            last_service_date=dt.date.today(),
        ),
        headers=headers,
    )
    assert low_created.status_code == high_created.status_code == 201

    flagged_at = dt.datetime.now(dt.timezone.utc)
    _score_from_inspection(factory, low_asset_id, manager_id, "Critical", flagged_at)
    _score_from_inspection(
        factory,
        high_asset_id,
        manager_id,
        "Critical",
        flagged_at + dt.timedelta(seconds=1),
    )

    queue = client.get("/api/v1/maintenance-queue?limit=1", headers=headers)
    assert queue.status_code == 200
    assert queue.headers["cache-control"] == "private, no-store"
    assert [item["assetId"] for item in queue.json()["items"]] == [low_asset_id]
    assert queue.json()["nextCursor"]

    second_page = client.get(
        (
            "/api/v1/maintenance-queue?limit=1"
            f"&cursor={queue.json()['nextCursor']}"
        ),
        headers=headers,
    )
    assert second_page.status_code == 200
    assert [item["assetId"] for item in second_page.json()["items"]] == [high_asset_id]
    assert client.get("/api/v1/maintenance-queue").status_code == 401

    _score_from_inspection(
        factory, low_asset_id, manager_id, "Excellent", flagged_at + dt.timedelta(minutes=1)
    )
    _score_from_inspection(
        factory, low_asset_id, manager_id, "Critical", flagged_at + dt.timedelta(minutes=2)
    )

    with migration.connect() as connection:
        episodes = connection.execute(
            text(
                "SELECT score_at_flag, resolved_at, resolved_score_id "
                "FROM alerts WHERE asset_id = :asset_id ORDER BY flagged_at, id"
            ),
            {"asset_id": low_asset_id},
        ).all()
        outbox_count = connection.execute(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE aggregate_id = :asset_id AND event_type = 'asset_flagged_email'"
            ),
            {"asset_id": low_asset_id},
        ).scalar_one()
        flagged_events = connection.execute(
            text(
                "SELECT count(*) FROM analytics_events "
                "WHERE event_name = 'asset_flagged' AND properties->>'asset_id' = :asset_id"
            ),
            {"asset_id": low_asset_id},
        ).scalar_one()

    assert len(episodes) == 2
    assert episodes[0].resolved_at is not None
    assert episodes[0].resolved_score_id is not None
    assert episodes[1].resolved_at is None
    assert Decimal(episodes[0].score_at_flag) < Decimal("40")
    assert outbox_count == 2
    assert flagged_events == 2
