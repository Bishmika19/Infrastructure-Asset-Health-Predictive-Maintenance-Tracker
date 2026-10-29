"""Security primitives: password hashing and signed bearer tokens (DEC-04, OD-07).

Only the standard library is used. Passwords are hashed with scrypt (adaptive:
the cost parameters are stored in each hash so they can be raised later and old
hashes still verify). Bearer tokens are compact HMAC-SHA256 signed documents
(``v1.<payload>.<signature>``) carrying subject, role, issue and expiry times.
Revocation of deactivated users is enforced by the principal dependency, which
re-checks ``users.is_active`` on each request.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from app.core.errors import Unauthenticated

# scrypt cost parameters (N=2**14, r=8, p=1 needs ~16 MiB, below OpenSSL's default cap).
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_SALT_BYTES = 16
_HASH_SCHEME = "scrypt"
TOKEN_VERSION = "v1"
MAX_PASSWORD_LENGTH = 256


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen, maxmem=128 * n * r * 2 + 1
    )


# PUBLIC_INTERFACE
def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random salt.

    Returns a self-describing string ``scrypt$N$r$p$salt$hash`` (base64url).
    """
    salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    return f"{_HASH_SCHEME}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64e(salt)}${_b64e(digest)}"


# PUBLIC_INTERFACE
def verify_password(password: str, stored_hash: str) -> bool:
    """Verify ``password`` against ``stored_hash`` in constant time.

    Malformed or unknown-scheme hashes verify as False rather than raising.
    """
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        scheme, n, r, p, salt, expected = stored_hash.split("$")
        if scheme != _HASH_SCHEME:
            return False
        expected_bytes = _b64d(expected)
        digest = _scrypt(password, _b64d(salt), int(n), int(r), int(p), len(expected_bytes))
    except (ValueError, TypeError, binascii.Error):
        return False
    return hmac.compare_digest(digest, expected_bytes)


# PUBLIC_INTERFACE
def password_needs_rehash(stored_hash: str) -> bool:
    """Return True when the stored hash uses weaker parameters than the current ones."""
    try:
        scheme, n, r, p, _, _ = stored_hash.split("$")
        return scheme != _HASH_SCHEME or (int(n), int(r), int(p)) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
    except ValueError:
        return True


# Hash verified for unknown usernames so response time does not reveal account existence.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


# PUBLIC_INTERFACE
def derive_key(secret: str, purpose: str) -> bytes:
    """Derive a purpose-specific signing key (domain separation for tokens and cursors)."""
    if not secret:
        raise ValueError("a signing secret is required")
    return hmac.new(secret.encode("utf-8"), f"asset-health:{purpose}".encode("utf-8"), "sha256").digest()


# PUBLIC_INTERFACE
def sign_document(key: bytes, document: dict) -> str:
    """Return ``<payload>.<signature>`` for a JSON-serializable document."""
    payload = _b64e(json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64e(hmac.new(key, payload.encode("ascii"), "sha256").digest())
    return f"{payload}.{signature}"


# PUBLIC_INTERFACE
def verify_document(key: bytes, signed: str) -> Optional[dict]:
    """Verify a signed document; returns the document or None when invalid or tampered."""
    try:
        payload, signature = signed.split(".")
        expected = _b64e(hmac.new(key, payload.encode("ascii"), "sha256").digest())
        if not hmac.compare_digest(signature, expected):
            return None
        document = json.loads(_b64d(payload))
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        return None
    return document if isinstance(document, dict) else None


@dataclass(frozen=True)
class TokenClaims:
    """Verified claims of a bearer token."""

    user_id: str
    role: str
    issued_at: int
    expires_at: int


# PUBLIC_INTERFACE
def issue_token(
    secret: str, user_id: str, role: str, ttl_s: int, now: Optional[float] = None
) -> str:
    """Issue a signed bearer token for ``user_id`` valid for ``ttl_s`` seconds."""
    issued = int(now if now is not None else time.time())
    claims = {"sub": user_id, "role": role, "iat": issued, "exp": issued + int(ttl_s)}
    return f"{TOKEN_VERSION}.{sign_document(derive_key(secret, 'token'), claims)}"


# PUBLIC_INTERFACE
def verify_token(secret: str, token: str, now: Optional[float] = None) -> TokenClaims:
    """Verify a bearer token and return its claims.

    Raises:
        Unauthenticated: the token is malformed, tampered with, or expired.
    """
    prefix, _, signed = token.partition(".")
    claims = verify_document(derive_key(secret, "token"), signed) if prefix == TOKEN_VERSION else None
    if claims is None:
        raise Unauthenticated("Invalid token")
    try:
        parsed = TokenClaims(
            user_id=str(claims["sub"]),
            role=str(claims["role"]),
            issued_at=int(claims["iat"]),
            expires_at=int(claims["exp"]),
        )
    except (KeyError, TypeError, ValueError):
        raise Unauthenticated("Invalid token") from None
    if parsed.expires_at <= int(now if now is not None else time.time()):
        raise Unauthenticated("Token expired")
    return parsed
