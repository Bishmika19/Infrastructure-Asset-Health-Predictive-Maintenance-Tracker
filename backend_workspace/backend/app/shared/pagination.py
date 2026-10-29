"""Signed keyset cursors (DEC-11, DEC-09).

A cursor binds the last keyset tuple, a fingerprint of the normalized filters,
and an optional upper bound. It is HMAC-signed, so it is never an offset or an
arbitrary SQL fragment, and tampering or filter changes yield 422 ``invalid_cursor``.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Mapping, Optional

from app.core.errors import InvalidCursor
from app.core.security import derive_key, sign_document, verify_document

MAX_CURSOR_LENGTH = 2048
DEFAULT_PAGE_LIMIT = 25
MAX_PAGE_LIMIT = 100


# PUBLIC_INTERFACE
def filters_fingerprint(filters: Mapping[str, Any]) -> str:
    """Return a stable fingerprint of the normalized filters a cursor is bound to."""
    canonical = json.dumps(
        {k: v for k, v in filters.items() if v is not None},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


# PUBLIC_INTERFACE
def encode_cursor(
    secret: str,
    kind: str,
    last: List[Any],
    filters: Mapping[str, Any],
    upper_bound: Optional[str] = None,
    now: Optional[float] = None,
) -> str:
    """Encode a signed cursor for list ``kind`` positioned after the keyset tuple ``last``."""
    document: Dict[str, Any] = {
        "k": kind,
        "l": last,
        "f": filters_fingerprint(filters),
        "u": upper_bound,
        "t": int(now if now is not None else time.time()),
    }
    return sign_document(derive_key(secret, "cursor"), document)


# PUBLIC_INTERFACE
def decode_cursor(
    secret: str,
    cursor: str,
    kind: str,
    filters: Mapping[str, Any],
    max_age_s: Optional[int] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Verify a cursor and return ``{"last": [...], "upper_bound": str | None}``.

    Raises:
        InvalidCursor: the cursor is too long, tampered with, for another list,
            bound to different filters, or older than ``max_age_s``.
    """
    if len(cursor) > MAX_CURSOR_LENGTH:
        raise InvalidCursor()
    document = verify_document(derive_key(secret, "cursor"), cursor)
    if (
        document is None
        or document.get("k") != kind
        or document.get("f") != filters_fingerprint(filters)
        or not isinstance(document.get("l"), list)
    ):
        raise InvalidCursor()
    if max_age_s is not None:
        issued = document.get("t")
        current = now if now is not None else time.time()
        if not isinstance(issued, int) or current - issued > max_age_s:
            raise InvalidCursor("Cursor expired")
    return {"last": document["l"], "upper_bound": document.get("u")}
