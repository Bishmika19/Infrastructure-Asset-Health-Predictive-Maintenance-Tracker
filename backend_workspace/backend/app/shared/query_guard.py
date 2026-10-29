"""Reject unknown or repeated query parameters with 400 (DEC-11, R-05).

FastAPI silently ignores undeclared query parameters. ``reject_bad_query_params``
is installed once as a router-level dependency: it derives the set of declared
query parameters from the matched route and rejects everything else, as well as
any parameter supplied more than once.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Set

from fastapi import Request
from fastapi.dependencies.utils import get_flat_dependant

from app.core.errors import InvalidRequest


# PUBLIC_INTERFACE
def check_query_params(received: Iterable[str], allowed: Set[str]) -> None:
    """Raise ``InvalidRequest`` for unknown or repeated query parameter names."""
    counts = Counter(received)
    unknown = sorted(name for name in counts if name not in allowed)
    if unknown:
        raise InvalidRequest(f"Unknown query parameter(s): {', '.join(unknown)}")
    repeated = sorted(name for name, count in counts.items() if count > 1)
    if repeated:
        raise InvalidRequest(f"Repeated query parameter(s): {', '.join(repeated)}")


def _declared_query_names(request: Request) -> Set[str]:
    route = request.scope.get("route")
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return set()
    return {param.alias for param in get_flat_dependant(dependant).query_params}


# PUBLIC_INTERFACE
def reject_bad_query_params(request: Request) -> None:
    """FastAPI dependency: 400 when the request has undeclared or repeated query parameters."""
    check_query_params(
        (key for key, _ in request.query_params.multi_items()), _declared_query_names(request)
    )
