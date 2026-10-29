"""Unit of work: commit on success, roll back on error, retry deadlocks (DEC-12)."""

from __future__ import annotations

import logging
from typing import Callable, Optional, TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

T = TypeVar("T")

MAX_DEADLOCK_ATTEMPTS = 3
# PostgreSQL SQLSTATEs: deadlock_detected, serialization_failure.
_RETRYABLE_SQLSTATES = {"40P01", "40001"}


def is_retryable(error: BaseException) -> bool:
    """Return True for recognized deadlock/serialization failures."""
    if not isinstance(error, DBAPIError):
        return False
    return getattr(error.orig, "sqlstate", None) in _RETRYABLE_SQLSTATES


class UnitOfWork:
    """Transaction scope owning one session; services never commit themselves."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self.session: Optional[Session] = None

    def __enter__(self) -> "UnitOfWork":
        self.session = self._factory()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self.session is not None
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None


# PUBLIC_INTERFACE
def run_in_transaction(
    factory: sessionmaker[Session],
    work: Callable[[Session], T],
    max_attempts: int = MAX_DEADLOCK_ATTEMPTS,
) -> T:
    """Run ``work(session)`` in one transaction, retrying recognized deadlocks."""
    attempt = 0
    while True:
        attempt += 1
        try:
            with UnitOfWork(factory) as uow:
                assert uow.session is not None
                return work(uow.session)
        except DBAPIError as error:
            if attempt >= max_attempts or not is_retryable(error):
                raise
            logger.warning("retrying transaction after deadlock (attempt %d)", attempt)
