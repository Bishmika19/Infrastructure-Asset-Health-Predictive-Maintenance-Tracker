"""Shared request mechanics: cursors, ETag, idempotency helpers, query guard, schema base."""

import pytest
from fastapi import Depends, FastAPI, Query
from fastapi.testclient import TestClient

from app.core.errors import InvalidCursor, InvalidRequest, PreconditionRequired
from app.core.middleware import RequestGuardMiddleware
from app.core.problem import register_problem_handlers
from app.shared.concurrency import format_etag, if_match_version, parse_if_match
from app.shared.deps import require_role
from app.shared.idempotency import (
    idempotency_key,
    request_fingerprint,
    validate_idempotency_key,
)
from app.shared.pagination import decode_cursor, encode_cursor, filters_fingerprint
from app.shared.principal import ROLE_ASSET_MANAGER, ROLE_MAINTENANCE_CREW, Principal
from app.shared.query_guard import check_query_params, reject_bad_query_params
from app.shared.schema_base import ApiModel

SECRET = "c" * 40


# --- cursors ---------------------------------------------------------------
def test_cursor_round_trip():
    filters = {"status": "Open", "assetId": None}
    cursor = encode_cursor(SECRET, "cases", ["2026-01-01T00:00:00Z", "abc"], filters, "bound", now=100)
    decoded = decode_cursor(SECRET, cursor, "cases", {"status": "Open"}, now=150)
    assert decoded == {"last": ["2026-01-01T00:00:00Z", "abc"], "upper_bound": "bound"}


def test_cursor_rejects_other_filters_kind_and_tampering():
    cursor = encode_cursor(SECRET, "cases", [1], {"status": "Open"})
    for args in (
        (cursor, "queue", {"status": "Open"}),
        (cursor, "cases", {"status": "Complete"}),
        (cursor[:-3] + "AAA", "cases", {"status": "Open"}),
        ("not-a-cursor", "cases", {"status": "Open"}),
    ):
        with pytest.raises(InvalidCursor):
            decode_cursor(SECRET, *args)
    with pytest.raises(InvalidCursor):
        decode_cursor("z" * 40, cursor, "cases", {"status": "Open"})


def test_cursor_length_and_expiry():
    with pytest.raises(InvalidCursor):
        decode_cursor(SECRET, "x" * 3000, "cases", {})
    cursor = encode_cursor(SECRET, "cases", [1], {}, now=100)
    with pytest.raises(InvalidCursor):
        decode_cursor(SECRET, cursor, "cases", {}, max_age_s=10, now=200)
    assert decode_cursor(SECRET, cursor, "cases", {}, max_age_s=500, now=200)["last"] == [1]


def test_filters_fingerprint_ignores_none_and_order():
    assert filters_fingerprint({"a": 1, "b": None}) == filters_fingerprint({"a": 1})
    assert filters_fingerprint({"a": 1, "b": 2}) == filters_fingerprint({"b": 2, "a": 1})


# --- ETag / If-Match --------------------------------------------------------
def test_etag_format_and_parse():
    assert format_etag(3) == '"v3"'
    assert parse_if_match('"v3"') == 3
    assert parse_if_match(' "v12" ') == 12


def test_missing_if_match_is_428():
    with pytest.raises(PreconditionRequired):
        parse_if_match(None)


@pytest.mark.parametrize("bad", ["*", 'W/"v1"', '"v1", "v2"', '"x1"', "v1", '"v0"', "", '"v01"'])
def test_bad_if_match_is_400(bad):
    with pytest.raises(InvalidRequest):
        parse_if_match(bad)


def test_format_etag_rejects_zero():
    with pytest.raises(ValueError):
        format_etag(0)


# --- idempotency helpers ----------------------------------------------------
def test_idempotency_key_validation():
    assert validate_idempotency_key("abc-123_~") == "abc-123_~"
    assert validate_idempotency_key("k" * 128)
    for bad in (None, "", " ", "has space", "k" * 129, "tab\t", "ünï"):
        with pytest.raises(InvalidRequest):
            validate_idempotency_key(bad)


def test_request_fingerprint_is_order_independent_and_sensitive():
    a = request_fingerprint({"x": 1, "y": None})
    assert a == request_fingerprint({"y": None, "x": 1})
    assert a != request_fingerprint({"x": 2, "y": None})
    assert a != request_fingerprint({"x": 1})


# --- query guard ------------------------------------------------------------
def test_check_query_params():
    check_query_params(["a", "b"], {"a", "b", "c"})
    with pytest.raises(InvalidRequest, match="Unknown"):
        check_query_params(["z"], {"a"})
    with pytest.raises(InvalidRequest, match="Repeated"):
        check_query_params(["a", "a"], {"a"})


class Echo(ApiModel):
    """Body used to test the schema base."""

    asset_id: str
    note: str = ""


def _app() -> FastAPI:
    app = FastAPI(dependencies=[Depends(reject_bad_query_params)])
    app.add_middleware(RequestGuardMiddleware, max_json_bytes=16384, max_multipart_bytes=1000)
    register_problem_handlers(app)

    @app.get("/items")
    def items(limit: int = Query(25, ge=1, le=100), status: str = "any"):
        return {"limit": limit, "status": status}

    @app.post("/echo")
    def echo(body: Echo):
        return body.model_dump(by_alias=True)

    @app.put("/etag")
    def etag(version: int = Depends(if_match_version), key: str = Depends(idempotency_key)):
        return {"version": version, "key": key}

    return app


def test_query_guard_through_http():
    client = TestClient(_app())
    assert client.get("/items?limit=5").json() == {"limit": 5, "status": "any"}
    unknown = client.get("/items?bogus=1")
    assert unknown.status_code == 400 and unknown.json()["code"] == "invalid_request"
    assert client.get("/items?limit=1&limit=2").status_code == 400
    assert client.get("/items?limit=0").status_code == 422


def test_schema_base_is_camel_case_strict_and_trimmed():
    client = TestClient(_app())
    ok = client.post("/echo", json={"assetId": "  P-1  "})
    assert ok.status_code == 200 and ok.json() == {"assetId": "P-1", "note": ""}
    assert client.post("/echo", json={"assetId": "P-1", "extra": 1}).status_code == 400


def test_header_dependencies_through_http():
    client = TestClient(_app())
    assert client.put("/etag", headers={"Idempotency-Key": "k"}).status_code == 428
    assert client.put("/etag", headers={"If-Match": "*", "Idempotency-Key": "k"}).status_code == 400
    assert client.put("/etag", headers={"If-Match": '"v2"'}).status_code == 400
    ok = client.put("/etag", headers={"If-Match": '"v2"', "Idempotency-Key": "k"})
    assert ok.json() == {"version": 2, "key": "k"}


# --- role guard -------------------------------------------------------------
def test_require_role_allows_and_denies():
    from uuid import uuid4

    from app.shared.deps import get_principal

    app = FastAPI()
    register_problem_handlers(app)
    holder = {}

    @app.get("/manager")
    def manager(p: Principal = Depends(require_role(ROLE_ASSET_MANAGER))):
        return {"user": p.username}

    app.dependency_overrides[get_principal] = lambda: holder["principal"]
    client = TestClient(app)
    holder["principal"] = Principal(uuid4(), "mgr", ROLE_ASSET_MANAGER)
    assert client.get("/manager").json() == {"user": "mgr"}
    holder["principal"] = Principal(uuid4(), "crew", ROLE_MAINTENANCE_CREW)
    denied = client.get("/manager")
    assert denied.status_code == 403 and denied.json()["code"] == "forbidden"
