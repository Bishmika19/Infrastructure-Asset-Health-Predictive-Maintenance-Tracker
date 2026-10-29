"""Login, principal resolution, throttling, audit and idempotency against the workspace PostgreSQL."""

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
from app.shared.idempotency import IdempotencyStore, StoredResponse
from app.shared.principal import ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW

PASSWORD = "Test-Passw0rd!"
PREFIX = "itest-"


@pytest.fixture(scope="module")
def db():
    """Yield (runtime factory, migration engine); skip when the database is unavailable."""
    base = get_settings()
    if not (base.database_url and base.migration_database_url):
        pytest.skip("database URLs are not configured")
    runtime = create_engine(base.database_url)
    migration = create_engine(base.migration_database_url)
    try:
        with migration.connect() as conn:
            conn.execute(text("SELECT 1 FROM users LIMIT 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("workspace database is not reachable or not migrated")
    yield sessionmaker(bind=runtime, expire_on_commit=False), migration
    with migration.begin() as conn:  # owner role may clean up what the runtime role cannot delete
        conn.execute(text("DELETE FROM idempotency_records WHERE operation LIKE 'itest.%'"))
        conn.execute(text("DELETE FROM audit_logs WHERE attempted_username LIKE :p"), {"p": PREFIX + "%"})
        conn.execute(text("DELETE FROM audit_logs WHERE actor_id IN "
                          "(SELECT id FROM users WHERE username LIKE :p)"), {"p": PREFIX + "%"})
        conn.execute(text("DELETE FROM users WHERE username LIKE :p"), {"p": PREFIX + "%"})
    runtime.dispose()
    migration.dispose()


def _settings(**overrides) -> Settings:
    base = get_settings()
    values = {**base.__dict__, "auth_token_secret": "t" * 40, **overrides}
    return Settings(**values)


def _user(factory, role=ROLE_ASSET_MANAGER, active=True):
    name = f"{PREFIX}{uuid.uuid4().hex[:10]}"
    with factory() as session:
        user = UserRepository(session).add(name, hash_password(PASSWORD), role)
        user.is_active = active
        session.commit()
        return name, user.id


def _client(factory, **settings):
    return TestClient(create_app(_settings(**settings), db_probe=lambda: True, session_factory=factory))


def _audit(migration, username):
    with migration.connect() as conn:
        return conn.execute(
            text("SELECT event_type, actor_kind, request_id, metadata FROM audit_logs "
                 "WHERE attempted_username = :u ORDER BY occurred_at, id"),
            {"u": username},
        ).all()


def test_login_me_and_audit(db):
    factory, migration = db
    name, user_id = _user(factory)
    client = _client(factory)
    response = client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["tokenType"] == "Bearer" and body["user"]["role"] == ROLE_ASSET_MANAGER
    assert response.headers["cache-control"] == "private, no-store"
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['accessToken']}"})
    assert me.status_code == 200 and me.json()["id"] == str(user_id)
    events = _audit(migration, name)
    assert [e[0] for e in events] == ["auth.login_succeeded"]
    assert events[0][1] == "user" and events[0][2]


def test_bad_credentials_are_401_and_audited_as_anonymous(db):
    factory, migration = db
    name, _ = _user(factory)
    client = _client(factory)
    wrong = client.post("/api/v1/auth/login", json={"username": name, "password": "nope"})
    unknown = client.post("/api/v1/auth/login", json={"username": PREFIX + "ghost", "password": "x"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == "unauthorized"
    assert wrong.headers["www-authenticate"] == "Bearer"
    events = _audit(migration, name)
    assert [(e[0], e[1], e[3]["reason"]) for e in events] == [
        ("auth.login_failed", "anonymous", "bad_password")
    ]


def test_missing_or_invalid_token_is_401(db):
    factory, _ = db
    client = _client(factory)
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"}).status_code == 401


def test_deactivated_user_loses_access_immediately(db):
    factory, migration = db
    name, user_id = _user(factory)
    client = _client(factory)
    token = client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD}).json()[
        "accessToken"
    ]
    with factory() as session:
        UserRepository(session).get(user_id).is_active = False
        session.commit()
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401
    relogin = client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
    assert relogin.status_code == 401


def test_expired_token_is_401(db):
    factory, _ = db
    name, _ = _user(factory, ROLE_MAINTENANCE_CREW)
    client = _client(factory, auth_token_ttl_s=-5)
    token = client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD}).json()[
        "accessToken"
    ]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_username_throttle_returns_429_with_retry_after_and_audits(db):
    factory, migration = db
    name, _ = _user(factory)
    client = _client(factory, login_max_failures_per_username=3, login_max_failures_per_ip=1000)
    for _ in range(3):
        bad = client.post("/api/v1/auth/login", json={"username": name, "password": "bad"})
        assert bad.status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1
    kinds = [e[0] for e in _audit(migration, name)]
    assert kinds == ["auth.login_failed"] * 3 + ["auth.login_throttled"]


def test_login_validation_errors(db):
    factory, _ = db
    client = _client(factory)
    assert client.post("/api/v1/auth/login", json={"username": "a"}).status_code == 400
    extra = client.post("/api/v1/auth/login", json={"username": "a", "password": "b", "x": 1})
    assert extra.status_code == 400
    unknown_query = client.post("/api/v1/auth/login?foo=1", json={"username": "a", "password": "b"})
    assert unknown_query.status_code == 400


def test_idempotency_store_replay_conflict_and_expiry(db):
    factory, _ = db
    _, user_id = _user(factory)
    op, key = "itest.create", uuid.uuid4().hex
    stored = StoredResponse(201, {"id": "1"}, {"ETag": '"v1"'})
    with factory() as session:
        store = IdempotencyStore(session, ttl_s=3600)
        assert store.lookup(user_id, op, key, "hash-a") is None
        store.save(user_id, op, key, "hash-a", stored)
        session.commit()
    with factory() as session:
        store = IdempotencyStore(session, ttl_s=3600)
        assert store.lookup(user_id, op, key, "hash-a") == stored
        from app.core.errors import IdempotencyConflict

        with pytest.raises(IdempotencyConflict):
            store.lookup(user_id, op, key, "hash-b")
        # A different principal-operation scope is independent.
        assert store.lookup(user_id, "itest.other", key, "hash-b") is None
        session.rollback()
    with factory() as session:  # expire the record, then the key can be reused
        session.execute(
            text("UPDATE idempotency_records SET created_at = :c, expires_at = :e WHERE key = :k"),
            {"c": dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
             "e": dt.datetime(2020, 1, 2, tzinfo=dt.timezone.utc), "k": key},
        )
        session.commit()
    with factory() as session:
        assert IdempotencyStore(session).lookup(user_id, op, key, "hash-b") is None
        session.commit()
