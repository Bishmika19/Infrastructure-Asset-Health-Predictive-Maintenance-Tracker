"""Pure forward-only work-order lifecycle rules (FR-6, DEC-10)."""

from __future__ import annotations

from typing import Optional

CASE_STATUSES = ("Open", "Assigned", "In Progress", "Complete")
NEXT_STATUS = {
    "Open": "Assigned",
    "Assigned": "In Progress",
    "In Progress": "Complete",
    "Complete": None,
}


# PUBLIC_INTERFACE
def next_status(status: str) -> Optional[str]:
    """Return the sole permitted next status, or ``None`` for a terminal Case."""
    return NEXT_STATUS.get(status)


# PUBLIC_INTERFACE
def is_next_transition(current: str, requested: str) -> bool:
    """Return whether ``requested`` is the sole forward transition from ``current``."""
    return next_status(current) == requested
