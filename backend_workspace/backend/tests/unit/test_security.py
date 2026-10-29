"""Password hashing and signed bearer tokens (DEC-04, OD-07)."""

import pytest

from app.core.errors import Unauthenticated
from app.core.security import (
    derive_key,
    hash_password,
    issue_token,
    password_needs_rehash,
    sign_document,
    verify_document,
    verify_password,
    verify_token,
)

SECRET = "s" * 40


def test_password_round_trip_and_wrong_password():
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong", stored)


def test_hashes_are_salted():
    assert hash_password("same") != hash_password("same")


@pytest.mark.parametrize("bad", ["", "plain", "bcrypt$1$2$3$a$b", "scrypt$x$8$1$AA$AA"])
def test_malformed_hash_verifies_false(bad):
    assert verify_password("pw", bad) is False
    assert password_needs_rehash(bad) is True


def test_overlong_password_is_rejected():
    assert verify_password("x" * 1000, hash_password("x")) is False


def test_current_hash_does_not_need_rehash():
    assert password_needs_rehash(hash_password("pw")) is False


def test_token_round_trip():
    token = issue_token(SECRET, "user-1", "asset_manager", 60, now=1000)
    claims = verify_token(SECRET, token, now=1030)
    assert (claims.user_id, claims.role, claims.expires_at) == ("user-1", "asset_manager", 1060)


def test_expired_token_is_unauthenticated():
    token = issue_token(SECRET, "u", "asset_manager", 60, now=1000)
    with pytest.raises(Unauthenticated):
        verify_token(SECRET, token, now=1060)


def test_tampered_or_foreign_tokens_are_rejected():
    token = issue_token(SECRET, "u", "maintenance_crew", 60, now=1000)
    head, payload, signature = token.split(".")
    for bad in (
        f"{head}.{payload}.{signature[:-2]}xx",
        f"{head}.{payload[:-2]}xx.{signature}",
        "garbage",
        "",
        token.replace("v1.", "v2.", 1),
    ):
        with pytest.raises(Unauthenticated):
            verify_token(SECRET, bad, now=1001)
    with pytest.raises(Unauthenticated):
        verify_token("t" * 40, token, now=1001)


def test_keys_are_domain_separated():
    assert derive_key(SECRET, "token") != derive_key(SECRET, "cursor")
    signed = sign_document(derive_key(SECRET, "cursor"), {"a": 1})
    assert verify_document(derive_key(SECRET, "cursor"), signed) == {"a": 1}
    assert verify_document(derive_key(SECRET, "token"), signed) is None
