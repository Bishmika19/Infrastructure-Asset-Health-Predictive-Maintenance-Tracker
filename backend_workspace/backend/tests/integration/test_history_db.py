"""PostgreSQL integration coverage for the authenticated asset-history timeline."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.main import create_app
from app.modules.alerts.models import Alert
from app.modules.assets.models import Asset
from app.modules.identity.repository import UserRepository
from app.modules.inspections.models import Inspection
from app.modules.scoring.models import HealthScoreHistory
from app.modules.work_orders.models import WorkOrder, WorkOrderStatusHistory
from app.shared.principal import ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW

PASSWORD = "Test-Passw0rd!"
PREFIX = "history-itest-"


@pytest.fixture(scope="module")
def db():
    """Yield runtime/migration database handles and remove isolated records afterward."""
    base = get_settings()
    if not (base.database_url and base.migration_database_url):
        pytest.skip("database URLs are not configured")

    runtime = create_engine(base.database_url)
    migration = create_engine(base.migration_database_url)
    try:
        with migration.connect() as connection:
            connection.execute(text("SELECT 1 FROM work_order_status_history LIMIT 1"))
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
                "DELETE FROM audit_logs WHERE entity_type = 'asset' "
                "AND entity_id LIKE :prefix"
            ),
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
            text(
                "DELETE FROM work_order_status_history WHERE work_order_id IN "
                "(SELECT id FROM work_orders WHERE asset_id LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM work_orders WHERE asset_id LIKE :prefix"),
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
            text("DELETE FROM inspections WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM assets WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM users WHERE username LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
    runtime.dispose()
    migration.dispose()


def _settings() -> Settings:
    """Return deterministic token-signing settings for history API tests."""
    base = get_settings()
    return Settings(**{**base.__dict__, "auth_token_secret": "h" * 40})


def _client(factory) -> TestClient:
    """Build a TestClient bound to the supplied PostgreSQL session factory."""
    return TestClient(create_app(_settings(), db_probe=lambda: True, session_factory=factory))


def _token(factory, role: str) -> tuple[str, uuid.UUID]:
    """Create and authenticate an isolated active user of the requested role."""
    username = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    with factory() as session:
        user = UserRepository(session).add(username, hash_password(PASSWORD), role)
        session.commit()
        user_id = user.id

    response = _client(factory).post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["accessToken"], user_id


def _asset_payload(asset_id: str) -> dict[str, str]:
    """Build a valid asset-create request for the timeline source fixture."""
    today = dt.date.today()
    return {
        "assetId": asset_id,
        "assetType": "Pump",
        "location": "History Test Yard",
        "installationDate": (today - dt.timedelta(days=365 * 10)).isoformat(),
        "manufacturer": "Acme",
        "lastServiceDate": today.isoformat(),
    }


def _insert_timeline_sources(
    factory,
    asset_id: str,
    manager_id: uuid.UUID,
    crew_id: uuid.UUID,
) -> None:
    """Persist each immutable history source at distinct deterministic instants."""
    base_time = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)

    with factory() as session:
        asset = session.get(Asset, asset_id)
        assert asset is not None

        inspection = Inspection(
            asset_id=asset_id,
            condition_rating="Critical",
            observations="Synthetic mixed-history inspection",
            inspector_id=crew_id,
            inspected_at=base_time,
        )
        session.add(inspection)
        session.flush()

        opening_score = HealthScoreHistory(
            asset_id=asset_id,
            inspection_id=inspection.id,
            score=10,
            color_band="Red",
            trigger_type="inspection",
            formula_version="v1",
            inputs={},
            calculated_at=base_time + dt.timedelta(seconds=1),
            actor_id=crew_id,
        )
        session.add(opening_score)
        session.flush()

        alert = Alert(
            asset_id=asset_id,
            opening_score_id=opening_score.id,
            score_at_flag=10,
            flagged_at=base_time + dt.timedelta(seconds=2),
            actor_id=crew_id,
        )
        session.add(alert)
        session.flush()

        resolved_score = HealthScoreHistory(
            asset_id=asset_id,
            inspection_id=None,
            score=80,
            color_band="Green",
            trigger_type="service_update",
            formula_version="v1",
            inputs={},
            calculated_at=base_time + dt.timedelta(seconds=3),
            actor_id=manager_id,
        )
        session.add(resolved_score)
        session.flush()
        alert.resolved_at = base_time + dt.timedelta(seconds=4)
        alert.resolved_score_id = resolved_score.id

        work_order = WorkOrder(
            asset_id=asset_id,
            alert_id=alert.id,
            asset_snapshot={
                "asset_id": asset.asset_id,
                "asset_type": asset.asset_type,
                "location": asset.location,
                "installation_date": asset.installation_date.isoformat(),
                "manufacturer": asset.manufacturer,
                "last_service_date": asset.last_service_date.isoformat(),
            },
            fault_description="Synthetic mixed-history maintenance request",
            priority="High",
            assignee_id=crew_id,
            status="Open",
            created_by=manager_id,
            created_at=base_time + dt.timedelta(seconds=5),
            updated_at=base_time + dt.timedelta(seconds=5),
        )
        session.add(work_order)
        session.flush()
        session.add(
            WorkOrderStatusHistory(
                work_order_id=work_order.id,
                previous_status=None,
                new_status="Open",
                actor_id=manager_id,
                changed_at=base_time + dt.timedelta(seconds=6),
                order_version=1,
            )
        )
        session.commit()


def test_asset_history_is_authenticated_paginated_and_observable(db) -> None:
    """Both roles can view chronological mixed sources; reads emit audit and analytics rows."""
    factory, migration = db
    client = _client(factory)
    manager_token, manager_id = _token(factory, ROLE_ASSET_MANAGER)
    crew_token, crew_id = _token(factory, ROLE_MAINTENANCE_CREW)
    asset_id = f"{PREFIX}{uuid.uuid4().hex[:12]}"

    created = client.post(
        "/api/v1/assets",
        json=_asset_payload(asset_id),
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert created.status_code == 201
    _insert_timeline_sources(factory, asset_id, manager_id, crew_id)

    assert client.get(f"/api/v1/assets/{asset_id}/history").status_code == 401

    headers = {"Authorization": f"Bearer {manager_token}"}
    first = client.get(f"/api/v1/assets/{asset_id}/history?limit=2", headers=headers)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, no-store"
    assert [item["eventKind"] for item in first.json()["items"]] == [
        "inspection_logged",
        "alert_opened",
    ]
    assert first.json()["items"][0]["actorId"] == str(crew_id)
    assert first.json()["items"][0]["details"] == {"conditionRating": "Critical"}
    assert first.json()["items"][1]["details"] == {"scoreAtFlag": "10.00"}

    second = client.get(
        f"/api/v1/assets/{asset_id}/history?limit=2&cursor={first.json()['nextCursor']}",
        headers=headers,
    )
    assert second.status_code == 200
    assert [item["eventKind"] for item in second.json()["items"]] == [
        "alert_resolved",
        "work_order_status_changed",
    ]
    assert second.json()["items"][1]["actorId"] == str(manager_id)
    assert second.json()["items"][1]["details"] == {
        "previousStatus": None,
        "newStatus": "Open",
    }

    crew_view = client.get(
        f"/api/v1/assets/{asset_id}/history",
        headers={"Authorization": f"Bearer {crew_token}"},
    )
    assert crew_view.status_code == 200
    assert client.get(
        f"/api/v1/assets/{asset_id}/history?cursor=not-a-cursor",
        headers=headers,
    ).status_code == 422
    assert client.get(
        f"/api/v1/assets/{asset_id}/history?limit=1&limit=1",
        headers=headers,
    ).status_code == 400

    with migration.connect() as connection:
        audit_rows = connection.execute(
            text(
                "SELECT metadata->>'viewerRole', request_id FROM audit_logs "
                "WHERE event_type = 'history.viewed' AND entity_type = 'asset' "
                "AND entity_id = :asset_id ORDER BY occurred_at, id"
            ),
            {"asset_id": asset_id},
        ).all()
        analytics_rows = connection.execute(
            text(
                "SELECT properties->>'viewer_role' FROM analytics_events "
                "WHERE event_name = 'asset_history_viewed' "
                "AND properties->>'asset_id' = :asset_id ORDER BY occurred_at, id"
            ),
            {"asset_id": asset_id},
        ).scalars().all()

    assert [row[0] for row in audit_rows] == [
        ROLE_ASSET_MANAGER,
        ROLE_ASSET_MANAGER,
        ROLE_MAINTENANCE_CREW,
    ]
    assert all(row[1] for row in audit_rows)
    assert analytics_rows == [
        ROLE_ASSET_MANAGER,
        ROLE_ASSET_MANAGER,
        ROLE_MAINTENANCE_CREW,
    ]
