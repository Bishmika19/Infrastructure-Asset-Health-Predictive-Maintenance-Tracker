"""Baseline tests for the application factory and health routes."""

from fastapi.testclient import TestClient

from app.main import create_app
from src.api.main import app as launcher_app
from src.api.settings import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        allowed_origins=["http://localhost:3000"],
        allowed_headers=["Content-Type"],
        allowed_methods=["GET"],
    )
    base.update(overrides)
    return Settings(**base)


def test_healthz_ok_when_database_usable():
    client = TestClient(create_app(_settings(), db_probe=lambda: True))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "backend", "database": "ok"}
    assert response.headers["x-request-id"]


def test_healthz_503_when_database_unusable():
    client = TestClient(create_app(_settings(), db_probe=lambda: False))
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_livez_does_not_need_database():
    client = TestClient(create_app(_settings(), db_probe=lambda: False))
    assert client.get("/livez").status_code == 200


def test_custom_healthcheck_path():
    client = TestClient(create_app(_settings(healthcheck_path="/ready"), db_probe=lambda: True))
    assert client.get("/ready").status_code == 200
    assert client.get("/healthz").status_code == 404


def test_cors_allows_configured_origin():
    client = TestClient(create_app(_settings(), db_probe=lambda: True))
    response = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_launcher_reexports_canonical_app():
    from app.main import app

    assert launcher_app is app
