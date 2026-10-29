"""Idempotency keys for create operations (DEC-11, HLD §8.3).

Usage inside the caller's unit of work::

    store = IdempotencyStore(session, ttl_s)
    replay = store.lookup(principal_id, "cases.create", key, fingerprint)
    if replay is not None:
        return replay            # original status, body and headers
    ...create the resource...
    store.save(principal_id, "cases.create", key, fingerprint, StoredResponse(201, body, headers))

``lookup`` takes a transaction-scoped advisory lock on the (principal, operation,
key) triple, so concurrent duplicates serialize: the second sees the committed
record and replays it. The stored response commits atomically with the resource.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Mapping, Optional

from fastapi import Header
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.errors import IdempotencyConflict, InvalidRequest
from app.shared.models import IdempotencyRecord

# 1-128 printable ASCII characters (space excluded, so keys are never blank).
_KEY_PATTERN = re.compile(r"^[\x21-\x7e]{1,128}$")


@dataclass(frozen=True)
class StoredResponse:
    """The exact success response persisted for replay."""

    status: int
    body: Dict[str, Any]
    headers: Dict[str, str]


# PUBLIC_INTERFACE
def validate_idempotency_key(key: Optional[str]) -> str:
    """Validate an ``Idempotency-Key`` value.

    Raises:
        InvalidRequest: the key is missing or not 1-128 printable ASCII characters (400).
    """
    if key is None or not _KEY_PATTERN.match(key):
        raise InvalidRequest("Idempotency-Key must be 1-128 printable ASCII characters")
    return key


# PUBLIC_INTERFACE
def idempotency_key(
    key: Annotated[
        Optional[str],
        Header(
            alias="Idempotency-Key",
            description="Client-generated key (1-128 printable ASCII) making the create safely retryable.",
        ),
    ] = None,
) -> str:
    """FastAPI dependency returning the validated ``Idempotency-Key`` header."""
    return validate_idempotency_key(key)


# PUBLIC_INTERFACE
def request_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash the normalized accepted request (including null defaults) for conflict detection."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class IdempotencyStore:
    """Reserve, replay and persist idempotent responses inside the caller's transaction."""

    def __init__(self, session: Session, ttl_s: int = 24 * 3600) -> None:
        self._session = session
        self._ttl = dt.timedelta(seconds=ttl_s)

    def _lock(self, principal_id: uuid.UUID, operation: str, key: str) -> None:
        """Serialize concurrent requests carrying the same key until the transaction ends."""
        lock_name = f"idem:{principal_id}:{operation}:{key}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": lock_name}
        )

    def lookup(
        self, principal_id: uuid.UUID, operation: str, key: str, fingerprint: str
    ) -> Optional[StoredResponse]:
        """Return the stored response for a replay, or None when the key is new or expired.

        Raises:
            IdempotencyConflict: the key was used before with a different request (409).
        """
        self._lock(principal_id, operation, key)
        record = self._session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.principal_id == principal_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        if record.expires_at <= _utcnow():
            # Expired: the key may be reused for a new create.
            self._session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.principal_id == principal_id,
                    IdempotencyRecord.operation == operation,
                    IdempotencyRecord.key == key,
                )
            )
            return None
        if record.request_hash != fingerprint:
            raise IdempotencyConflict()
        return StoredResponse(record.response_status, record.response_body, record.response_headers)

    def save(
        self,
        principal_id: uuid.UUID,
        operation: str,
        key: str,
        fingerprint: str,
        response: StoredResponse,
    ) -> None:
        """Persist the success response; commits with the resource it describes."""
        now = _utcnow()
        self._session.add(
            IdempotencyRecord(
                principal_id=principal_id,
                operation=operation,
                key=key,
                request_hash=fingerprint,
                response_body=response.body,
                response_headers=response.headers,
                response_status=response.status,
                created_at=now,
                expires_at=now + self._ttl,
            )
        )
        self._session.flush()
