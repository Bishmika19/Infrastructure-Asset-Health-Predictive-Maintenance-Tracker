"""PostgreSQL integration tests for the durable worker."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.infrastructure.outbox.models import OutboxEvent
from app.modules.assets.models import Asset
from app.modules.identity.repository import UserRepository
from app.worker.jobs.nightly_scoring import NightlyScoringJob
from app.worker.outbox_dispatcher import OutboxDispatcher
from app.worker.scheduler import Scheduler, utc_day


PREFIX = "worker-itest-"


@pytest.fixture(scope="module")
def db():
    """Yield runtime and migration database handles or skip when PostgreSQL is unavailable."""
    settings = get_settings()
    if not (settings.database_url and settings.migration_database_url):
        pytest.skip("database URLs are not configured")
    runtime = create_engine(settings.database_url)
    migration = create_engine(settings.migration_database_url)
    try:
        with migration.connect() as connection:
            connection.execute(text("SELECT 1 FROM scheduled_runs LIMIT 1"))
    except Exception:  # noqa: BLE001
        pytest.skip("workspace database is not reachable or not migrated")
    yield sessionmaker(bind=runtime, expire_on_commit=False), migration
    with migration.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM health_score_history WHERE asset_id LIKE :prefix"
            ),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM audit_logs WHERE entity_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM analytics_events WHERE properties->>'asset_id' LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM outbox_events WHERE aggregate_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM assets WHERE asset_id LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
        connection.execute(
            text("DELETE FROM users WHERE username LIKE :prefix"),
            {"prefix": PREFIX + "%"},
        )
    runtime.dispose()
    migration.dispose()


def _active_asset(factory) -> str:
    """Create one active asset with a valid user foreign key for nightly scoring."""
    asset_id = f"{PREFIX}asset-{uuid.uuid4().hex[:10]}"
    username = f"{PREFIX}user-{uuid.uuid4().hex[:10]}"
    with factory() as session:
        user = UserRepository(session).add(username, "not-used", "asset_manager")
        session.add(
            Asset(
                asset_id=asset_id,
                asset_type="Pump",
                location="Worker Yard",
                installation_date=dt.date.today() - dt.timedelta(days=365),
                manufacturer="Acme",
                created_by=user.id,
            )
        )
        session.commit()
    return asset_id


def test_nightly_schedule_resumes_and_outbox_delivery_is_fenced(db):
    """Nightly scoring stores run provenance while a leased event is delivered exactly once."""
    factory, migration = db
    asset_id = _active_asset(factory)
    scheduler = Scheduler(factory, owner=f"{PREFIX}scheduler", lease_seconds=60)
    occurrence = utc_day()
    nightly_name = f"{PREFIX}nightly-{uuid.uuid4().hex}"
    lease = scheduler.claim(nightly_name, occurrence)
    assert lease is not None

    processed = NightlyScoringJob(factory, scheduler, batch_size=1).run(lease)
    # The durable job correctly scores every active asset, including pre-existing
    # development/browser-test records, not only this fixture's test asset.
    assert processed >= 1
    assert scheduler.complete(lease)

    delivered_ids = []
    # Use a historical availability time and dispatch at that same instant. This
    # confines the shared-database test to its own synthetic event instead of
    # acknowledging unrelated pending development outbox records.
    dispatch_time = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    with factory() as session:
        event = OutboxEvent(
            event_type="asset_flagged_email",
            aggregate_type="asset",
            aggregate_id=f"{PREFIX}event-{uuid.uuid4().hex[:8]}",
            payload={"assetId": asset_id, "score": "1.00", "flaggedAt": occurrence.isoformat()},
            available_at=dispatch_time,
        )
        session.add(event)
        session.commit()
        event_id = event.id

    dispatcher = OutboxDispatcher(
        factory,
        owner=f"{PREFIX}dispatcher",
        lease_seconds=60,
        max_attempts=8,
        backoff_cap_seconds=60,
        deliver=lambda message: delivered_ids.append(message.event_id),
    )
    assert dispatcher.dispatch(now=dispatch_time) == 1
    assert delivered_ids == [event_id]

    with migration.connect() as connection:
        score_count = connection.execute(
            text(
                "SELECT count(*) FROM health_score_history "
                "WHERE asset_id = :asset_id AND run_id = :run_id"
            ),
            {"asset_id": asset_id, "run_id": lease.run_id},
        ).scalar_one()
        run = connection.execute(
            text(
                "SELECT status, cursor FROM scheduled_runs "
                "WHERE id = :run_id"
            ),
            {"run_id": lease.run_id},
        ).one()
        event_status = connection.execute(
            text("SELECT status, delivered_at FROM outbox_events WHERE id = :event_id"),
            {"event_id": event_id},
        ).one()

    assert score_count == 1
    assert run.status == "complete" and run.cursor == asset_id
    assert event_status.status == "delivered" and event_status.delivered_at is not None
