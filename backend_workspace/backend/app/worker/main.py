"""Worker runtime entrypoint: ``python -m app.worker.main``."""

from __future__ import annotations

import argparse
import logging
import socket
import time
import uuid
from typing import Optional

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db import registry as _model_registry  # noqa: F401 - register all ORM mappings.
from app.db.session import get_session_factory
from app.infrastructure.mail.smtp import SmtpMailSender
from app.infrastructure.storage.local import LocalPhotoStorage
from app.worker.freshness import FreshnessReporter
from app.worker.jobs.nightly_scoring import NightlyScoringJob
from app.worker.jobs.photo_sweeper import PhotoSweeper
from app.worker.outbox_dispatcher import OutboxDeliverySuppressed, OutboxDispatcher, OutboxLease
from app.worker.scheduler import Scheduler, utc_day

logger = logging.getLogger(__name__)

JOB_NIGHTLY_SCORING = "nightly_scoring"
JOB_PHOTO_SWEEPER = "photo_sweeper"


class WorkerRuntime:
    """Coordinate durable background work from the backend artifact."""

    def __init__(self, settings: Settings, owner: Optional[str] = None) -> None:
        """Build runtime dependencies from injected settings."""
        self._settings = settings
        self._owner = owner or f"{socket.gethostname()}-{uuid.uuid4()}"
        self._factory = get_session_factory()
        self._scheduler = Scheduler(self._factory, self._owner, settings.worker_lease_s)
        self._nightly = NightlyScoringJob(
            self._factory,
            self._scheduler,
            settings.worker_nightly_batch_size,
        )
        self._sweeper = PhotoSweeper(
            LocalPhotoStorage(settings.photo_storage_root),
            settings.worker_staging_ttl_s,
        )
        sender = SmtpMailSender(settings)
        self._dispatcher = OutboxDispatcher(
            self._factory,
            self._owner,
            settings.worker_lease_s,
            settings.outbox_max_attempts,
            settings.outbox_backoff_cap_s,
            lambda lease: self._deliver(sender, lease),
        )
        self._freshness = FreshnessReporter(self._factory)

    # PUBLIC_INTERFACE
    def run_once(self) -> None:
        """Run one database-leased work cycle without in-process cron scheduling."""
        occurrence = utc_day()
        self._run_nightly(occurrence)
        self._run_sweeper(occurrence)
        delivered = self._dispatcher.dispatch()
        freshness = self._freshness.emit()
        logger.info(
            "worker_cycle_complete delivered=%d last_nightly=%s oldest_outbox=%s",
            delivered,
            freshness.last_nightly_completed_at,
            freshness.oldest_pending_outbox_at,
        )

    # PUBLIC_INTERFACE
    def run_forever(self) -> None:
        """Run durable cycles until the worker process is stopped."""
        while True:
            self.run_once()
            time.sleep(max(1, self._settings.worker_poll_interval_s))

    def _run_nightly(self, occurrence) -> None:
        """Run the daily scoring job after successfully claiming its schedule lease."""
        lease = self._scheduler.claim(JOB_NIGHTLY_SCORING, occurrence)
        if lease is None:
            return
        try:
            processed = self._nightly.run(lease)
            if not self._scheduler.complete(lease):
                raise RuntimeError("nightly scoring lease was fenced before completion")
            logger.info("nightly_scoring_complete run_id=%s processed=%d", lease.run_id, processed)
        except Exception:  # noqa: BLE001 - retain cursor for durable recovery
            self._scheduler.fail(lease)
            logger.exception("nightly_scoring_failed run_id=%s", lease.run_id)

    def _run_sweeper(self, occurrence) -> None:
        """Run daily staged-photo cleanup after successfully claiming its lease."""
        lease = self._scheduler.claim(JOB_PHOTO_SWEEPER, occurrence)
        if lease is None:
            return
        try:
            removed = self._sweeper.run()
            if not self._scheduler.complete(lease):
                raise RuntimeError("photo sweeper lease was fenced before completion")
            logger.info("photo_sweeper_complete run_id=%s removed=%d", lease.run_id, removed)
        except Exception:  # noqa: BLE001 - retry cleanup using the retained schedule row
            self._scheduler.fail(lease)
            logger.exception("photo_sweeper_failed run_id=%s", lease.run_id)

    def _deliver(self, sender: SmtpMailSender, lease: OutboxLease) -> None:
        """Route allow-listed outbox events to their external delivery adapter."""
        if lease.event_type != "asset_flagged_email":
            raise ValueError(f"unsupported outbox event type: {lease.event_type}")
        if not self._settings.outbound_email_enabled:
            raise OutboxDeliverySuppressed("outbound email is disabled by configuration")
        sender.send_asset_flagged(lease.event_id, lease.payload)


# PUBLIC_INTERFACE
def main(argv: Optional[list[str]] = None) -> int:
    """Run the worker or validate its database-backed configuration.

    Parameters:
        argv: Optional CLI arguments. ``--check`` validates setup without
            claiming work, and ``--once`` runs a single durable cycle.

    Returns:
        Zero when the requested action completed successfully.
    """
    parser = argparse.ArgumentParser(description="Asset-health durable worker")
    parser.add_argument("--check", action="store_true", help="validate configuration without work")
    parser.add_argument("--once", action="store_true", help="run exactly one durable work cycle")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.database_url:
        parser.error("DATABASE_URL is required for the worker")
    if args.check:
        logger.info("worker_configuration_valid smtp_configured=%s", bool(settings.smtp_host))
        return 0

    runtime = WorkerRuntime(settings)
    if args.once:
        runtime.run_once()
    else:
        runtime.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
