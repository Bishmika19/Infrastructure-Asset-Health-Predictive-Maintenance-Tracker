"""Transport guards and problem+json mapping (AC-18 foundations)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.errors import NotFound
from app.core.middleware import RequestGuardMiddleware
from app.core.problem import register_problem_handlers


class Body(BaseModel):
    """Strict body used to exercise the validation mapping."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3)


def _client() -> TestClient:
    settings = Settings()
    app = FastAPI()
    app.add_middleware(
        RequestGuardMiddleware,
        max_json_bytes=settings.max_json_body_bytes,
        max_multipart_bytes=settings.max_multipart_body_bytes,
    )
    register_problem_handlers(app)

    @app.post("/echo")
    def echo(body: Body):
        return {"name": body.name}

    @app.get("/missing")
    def missing():
        raise NotFound("nothing here")

    @app.get("/boom")
    def boom():
        raise RuntimeError("SELECT secret FROM users")

    return TestClient(app, raise_server_exceptions=False)


def test_extra_field_is_400():
    response = _client().post("/echo", json={"name": "abc", "other": 1})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


def test_malformed_json_is_400():
    response = _client().post(
        "/echo", content=b"{bad", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400


def test_value_error_is_422():
    response = _client().post("/echo", json={"name": "a"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


def test_body_over_16kib_is_413():
    response = _client().post("/echo", json={"name": "x" * 20000})
    assert response.status_code == 413


def test_non_json_content_type_is_415():
    response = _client().post("/echo", content=b"name=abc", headers={"Content-Type": "text/plain"})
    assert response.status_code == 415


def test_domain_error_maps_to_problem_json():
    response = _client().get("/missing")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"
    assert response.json()["requestId"]


def test_unhandled_error_does_not_leak():
    response = _client().get("/boom")
    assert response.status_code == 500
    assert "SELECT" not in response.text
