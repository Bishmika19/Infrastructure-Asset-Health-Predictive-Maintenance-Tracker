"""Case/work-order PostgreSQL integration tests against the workspace database."""

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
from app.modules.identity.repository import UserRepository
from app.modules.inspections.models import Inspection
from app.modules.scoring.service import ScoringService
from app.shared.principal import Actor, ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW

PASSWORD = "Test-Passw0rd!"
PREFIX = "case-itest-"


@pytest.fixture(scope="module")
def db():
    """Yield database handles and remove this module's isolated records after tests."""
    base = get_settings()
    if not (base.database_url and base.migration_database_url):
        pytest.skip("database URLs are not configured")

    runtime = create_engine(base.database_url)
    migration = create_engine(base.migration_database_url)
    try:
        with migration.connect() as connection:
            connection.execute(text("SELECT 1 FROM work_orders LIMIT 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("workspace database is not reachable or not migrated")

    yield sessionmaker(bind=runtime, expire_on_commit=False), migration

    with migration.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM outbox_events "
                "WHERE aggregate_type = 'work_order' "
                "AND aggregate_id IN ("
                "SELECT id::text FROM work_orders WHERE asset_id LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text(
                "DELETE FROM analytics_events "
                "WHERE properties->>'asset_id' LIKE :prefix"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text(
                "DELETE FROM audit_logs "
                "WHERE entity_type = 'work_order' "
                "AND entity_id IN ("
                "SELECT id::text FROM work_orders WHERE asset_id LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text(
                "DELETE FROM work_order_status_history "
                "WHERE work_order_id IN ("
                "SELECT id FROM work_orders WHERE asset_id LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM work_orders WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM outbox_events WHERE aggregate_id LIKE :prefix"),
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
            text(
                "DELETE FROM audit_logs WHERE actor_id IN "
                "(SELECT id FROM users WHERE username LIKE :prefix)"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text(
                "DELETE FROM idempotency_records WHERE principal_id IN "
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


def _settings() -> Settings:
    """Return deterministic signing settings for TestClient authentication."""
    base = get_settings()
    return Settings(**{**base.__dict__, "auth_token_secret": "c" * 40})


def _client(factory) -> TestClient:
    """Create a client using the supplied PostgreSQL session factory."""
    return TestClient(create_app(_settings(), db_probe=lambda: True, session_factory=factory))


def _user(factory, role: str) -> tuple[str, uuid.UUID]:
    """Insert one active synthetic user and return its login name and stable ID."""
    username = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    with factory() as session:
        user = UserRepository(session).add(username, hash_password(PASSWORD), role)
        session.commit()
        return username, user.id


def _token(factory, role: str) -> tuple[str, uuid.UUID]:
    """Create and authenticate a synthetic user of the requested role."""
    username, user_id = _user(factory, role)
    response = _client(factory).post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["accessToken"], user_id


def _asset_payload(asset_id: str) -> dict[str, str]:
    """Build an asset payload whose critical inspection produces an open alert."""
    today = dt.date.today()
    return {
        "assetId": asset_id,
        "assetType": "Pump",
        "location": "Case Test Yard",
        "installationDate": (today - dt.timedelta(days=365 * 30)).isoformat(),
        "manufacturer": "Acme",
        "lastServiceDate": today.isoformat(),
    }


def _flagged_asset(factory, client: TestClient, manager_token: str, manager_id: uuid.UUID) -> str:
    """Create an asset and persist a critical inspection/score in one service transaction."""
    asset_id = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    response = client.post(
        "/api/v1/assets",
        json=_asset_payload(asset_id),
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert response.status_code == 201

    with factory() as session:
        inspection = Inspection(
            asset_id=asset_id,
            condition_rating="Critical",
            observations="Synthetic Case test inspection",
            inspector_id=manager_id,
            inspected_at=dt.datetime.now(dt.timezone.utc),
        )
        session.add(inspection)
        session.flush()
        ScoringService(session).recalculate(
            asset_id,
            "inspection",
            actor=Actor(kind="user", id=manager_id),
            inspection_id=inspection.id,
            now=inspection.inspected_at,
        )
        session.commit()
    return asset_id


def _create_case(
    client: TestClient,
    manager_token: str,
    asset_id: str,
    key: str,
    *,
    assignee_id: uuid.UUID | None = None,
    priority: str = "High",
) -> TestClient:
    """Create a Case request with the mandatory idempotency and manager headers."""
    payload: dict[str, str] = {
        "assetId": asset_id,
        "faultDescription": "Synthetic seal leakage",
        "priority": priority,
    }
    if assignee_id is not None:
        payload["assigneeId"] = str(assignee_id)
    return client.post(
        "/api/v1/cases",
        json=payload,
        headers={
            "Authorization": f"Bearer {manager_token}",
            "Idempotency-Key": key,
        },
    )


def test_case_create_replay_and_side_effects(db) -> None:
    """Creation stores a snapshot, replay response, history, audit, analytics, and outbox row."""
    factory, migration = db
    client = _client(factory)
    manager_token, manager_id = _token(factory, ROLE_ASSET_MANAGER)
    crew_token, crew_id = _token(factory, ROLE_MAINTENANCE_CREW)
    asset_id = _flagged_asset(factory, client, manager_token, manager_id)
    key = uuid.uuid4().hex

    created = _create_case(client, manager_token, asset_id, key, assignee_id=crew_id)
    assert created.status_code == 201
    assert created.headers["etag"] == '"v1"'
    assert created.headers["location"] == f"/api/v1/cases/{created.json()['id']}"
    assert created.headers["cache-control"] == "private, no-store"
    assert created.json()["status"] == "Open"
    assert created.json()["assigneeId"] == str(crew_id)
    assert created.json()["assetSnapshot"]["assetId"] == asset_id

    replay = _create_case(client, manager_token, asset_id, key, assignee_id=crew_id)
    assert replay.status_code == 201
    assert replay.json() == created.json()
    assert replay.headers["etag"] == created.headers["etag"]
    assert replay.headers["location"] == created.headers["location"]

    conflict = _create_case(
        client,
        manager_token,
        asset_id,
        key,
        assignee_id=crew_id,
        priority="Critical",
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"

    crew_create = _create_case(client, crew_token, asset_id, uuid.uuid4().hex)
    assert crew_create.status_code == 403

    with migration.connect() as connection:
        case_id = created.json()["id"]
        history = connection.execute(
            text(
                "SELECT previous_status, new_status, order_version "
                "FROM work_order_status_history WHERE work_order_id = :case_id"
            ),
            {"case_id": case_id},
        ).one()
        audit_events = connection.execute(
            text(
                "SELECT event_type FROM audit_logs "
                "WHERE entity_type = 'work_order' AND entity_id = :case_id"
            ),
            {"case_id": case_id},
        ).scalars().all()
        analytics = connection.execute(
            text(
                "SELECT event_name FROM analytics_events "
                "WHERE properties->>'work_order_id' = :case_id"
            ),
            {"case_id": case_id},
        ).scalars().all()
        outbox = connection.execute(
            text(
                "SELECT event_type FROM outbox_events "
                "WHERE aggregate_type = 'work_order' AND aggregate_id = :case_id"
            ),
            {"case_id": case_id},
        ).scalars().all()

    assert history == (None, "Open", 1)
    assert audit_events == ["work_order.created"]
    assert analytics == ["work_order_created"]
    assert outbox == ["work_order_created"]


def test_case_lifecycle_rbac_etags_and_status_history(db) -> None:
    """Lifecycle transitions are serialized, actor-restricted, and durably attributed."""
    factory, migration = db
    client = _client(factory)
    manager_token, manager_id = _token(factory, ROLE_ASSET_MANAGER)
    crew_token, crew_id = _token(factory, ROLE_MAINTENANCE_CREW)
    other_crew_token, _ = _token(factory, ROLE_MAINTENANCE_CREW)
    asset_id = _flagged_asset(factory, client, manager_token, manager_id)

    created = _create_case(
        client,
        manager_token,
        asset_id,
        uuid.uuid4().hex,
        assignee_id=crew_id,
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    manager_headers = {"Authorization": f"Bearer {manager_token}"}
    crew_headers = {"Authorization": f"Bearer {crew_token}"}
    other_crew_headers = {"Authorization": f"Bearer {other_crew_token}"}

    premature_crew = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"status": "Assigned"},
        headers={**crew_headers, "If-Match": '"v1"'},
    )
    assert premature_crew.status_code == 403

    assigned = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"status": "Assigned"},
        headers={**manager_headers, "If-Match": '"v1"'},
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "Assigned"
    assert assigned.headers["etag"] == '"v2"'

    non_assignee = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"status": "In Progress"},
        headers={**other_crew_headers, "If-Match": '"v2"'},
    )
    assert non_assignee.status_code == 403

    in_progress = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"status": "In Progress"},
        headers={**crew_headers, "If-Match": '"v2"'},
    )
    assert in_progress.status_code == 200
    assert in_progress.headers["etag"] == '"v3"'

    stale = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"priority": "Low"},
        headers={**manager_headers, "If-Match": '"v1"'},
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "precondition_failed"

    completed = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"status": "Complete"},
        headers={**crew_headers, "If-Match": '"v3"'},
    )
    assert completed.status_code == 200
    assert completed.headers["etag"] == '"v4"'
    assert completed.json()["status"] == "Complete"

    terminal = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"priority": "Low"},
        headers={**manager_headers, "If-Match": '"v4"'},
    )
    assert terminal.status_code == 409
    assert terminal.json()["code"] == "case_complete"

    with migration.connect() as connection:
        history = connection.execute(
            text(
                "SELECT new_status, order_version "
                "FROM work_order_status_history "
                "WHERE work_order_id = :case_id ORDER BY order_version"
            ),
            {"case_id": case_id},
        ).all()
        analytics_count = connection.execute(
            text(
                "SELECT count(*) FROM analytics_events "
                "WHERE event_name = 'work_order_status_changed' "
                "AND properties->>'work_order_id' = :case_id"
            ),
            {"case_id": case_id},
        ).scalar_one()
        outbox_count = connection.execute(
            text(
                "SELECT count(*) FROM outbox_events "
                "WHERE event_type = 'work_order_status_changed' "
                "AND aggregate_id = :case_id"
            ),
            {"case_id": case_id},
        ).scalar_one()

    assert history == [
        ("Open", 1),
        ("Assigned", 2),
        ("In Progress", 3),
        ("Complete", 4),
    ]
    assert analytics_count == 3
    assert outbox_count == 3


def test_case_fetch_list_cursor_and_query_guard(db) -> None:
    """Both roles can read stable Case pages while invalid cursor/query forms are rejected."""
    factory, _ = db
    client = _client(factory)
    manager_token, manager_id = _token(factory, ROLE_ASSET_MANAGER)
    crew_token, _ = _token(factory, ROLE_MAINTENANCE_CREW)
    asset_id = _flagged_asset(factory, client, manager_token, manager_id)

    first = _create_case(client, manager_token, asset_id, uuid.uuid4().hex)
    second = _create_case(client, manager_token, asset_id, uuid.uuid4().hex)
    assert first.status_code == second.status_code == 201

    manager_headers = {"Authorization": f"Bearer {manager_token}"}
    crew_headers = {"Authorization": f"Bearer {crew_token}"}
    fetched = client.get(f"/api/v1/cases/{first.json()['id']}", headers=crew_headers)
    assert fetched.status_code == 200
    assert fetched.headers["etag"] == '"v1"'
    assert fetched.json()["id"] == first.json()["id"]

    page = client.get("/api/v1/cases?limit=1", headers=manager_headers)
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["nextCursor"]

    following = client.get(
        f"/api/v1/cases?limit=1&cursor={page.json()['nextCursor']}",
        headers=manager_headers,
    )
    assert following.status_code == 200
    assert len(following.json()["items"]) == 1
    assert following.json()["items"][0]["id"] != page.json()["items"][0]["id"]

    assert client.get("/api/v1/cases").status_code == 401
    assert client.get("/api/v1/cases?cursor=not-a-valid-cursor", headers=manager_headers).status_code == 422
    assert client.get("/api/v1/cases?limit=1&limit=1", headers=manager_headers).status_code == 400
