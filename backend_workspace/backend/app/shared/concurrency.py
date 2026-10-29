"""Strong ETag formatting and ``If-Match`` parsing for optimistic concurrency (DEC-11)."""

from __future__ import annotations

import re
from typing import Annotated, Optional

from fastapi import Header

from app.core.errors import InvalidRequest, PreconditionRequired

# Exactly one strong version tag such as "v3" (no weak W/, no wildcard, no lists).
_STRONG_VERSION_TAG = re.compile(r'^"v([1-9][0-9]{0,9})"$')


# PUBLIC_INTERFACE
def format_etag(version: int) -> str:
    """Format a row version as a strong ETag, e.g. ``3`` -> ``"v3"``."""
    if version < 1:
        raise ValueError("version must be >= 1")
    return f'"v{version}"'


# PUBLIC_INTERFACE
def parse_if_match(header: Optional[str]) -> int:
    """Parse an ``If-Match`` header into the expected row version.

    Raises:
        PreconditionRequired: the header is absent (428).
        InvalidRequest: the header is blank, weak, a wildcard, a list, or malformed (400).
    """
    if header is None:
        raise PreconditionRequired()
    match = _STRONG_VERSION_TAG.match(header.strip())
    if match is None:
        raise InvalidRequest("If-Match must be exactly one strong version ETag such as \"v3\"")
    return int(match.group(1))


# PUBLIC_INTERFACE
def if_match_version(
    if_match: Annotated[
        Optional[str],
        Header(
            alias="If-Match",
            description='Strong version ETag of the resource being updated, e.g. `"v3"`.',
        ),
    ] = None,
) -> int:
    """FastAPI dependency returning the expected version from ``If-Match`` (428 when absent)."""
    return parse_if_match(if_match)
