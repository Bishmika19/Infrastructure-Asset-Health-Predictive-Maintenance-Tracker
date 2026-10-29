"""Focused unit tests for durable worker helpers and adapters."""

import datetime as dt
import os
import uuid
from pathlib import Path

from app.core.config import Settings
from app.infrastructure.mail.smtp import SmtpMailSender
from app.infrastructure.storage.local import LocalPhotoStorage
from app.worker.outbox_dispatcher import retry_delay_seconds
from app.worker.scheduler import utc_day


def test_utc_day_normalizes_an_arbitrary_timezone_aware_timestamp():
    """Daily schedule identities are stable across worker time zones."""
    local = dt.datetime(2026, 10, 29, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    assert utc_day(local) == dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc)


def test_retry_delay_is_exponential_and_capped():
    """Outbox failure retries back off without unbounded delays."""
    assert retry_delay_seconds(1, 60) == 5
    assert retry_delay_seconds(2, 60) == 10
    assert retry_delay_seconds(10, 60) == 60


def test_local_storage_sweeps_only_old_staged_files(tmp_path: Path):
    """The worker removes abandoned staging bytes but preserves final and recent objects."""
    storage = LocalPhotoStorage(tmp_path)
    old_stage = tmp_path / "staging" / "old"
    recent_stage = tmp_path / "staging" / "recent"
    final = tmp_path / "photos" / "final.jpg"
    for path in (old_stage, recent_stage, final):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bytes")
    old_time = (dt.datetime.now().timestamp() - 3600, ) * 2
    os.utime(old_stage, old_time)

    assert storage.sweep_staged(older_than=60) == 1
    assert not old_stage.exists()
    assert recent_stage.exists()
    assert final.exists()


def test_smtp_sender_uses_a_stable_outbox_message_id():
    """Repeated at-least-once attempts use the same email Message-ID."""
    messages = []

    class FakeSmtp:
        """In-memory SMTP client capturing the generated message."""

        def __init__(self, *args, **kwargs):
            """Accept the standard SMTP constructor parameters."""
            self.args = args
            self.kwargs = kwargs

        def __enter__(self):
            """Return the fake client."""
            return self

        def __exit__(self, *args):
            """Support SMTP context-manager cleanup."""
            return None

        def ehlo(self):
            """Accept EHLO calls."""
            return None

        def starttls(self):
            """Accept STARTTLS calls."""
            return None

        def login(self, username, password):
            """Accept configured credential use."""
            return (username, password)

        def send_message(self, message):
            """Capture the message sent by the adapter."""
            messages.append(message)

    event_id = uuid.uuid4()
    sender = SmtpMailSender(
        Settings(
            smtp_host="smtp.example.test",
            smtp_to=["maintenance@example.test"],
            smtp_starttls=False,
        ),
        smtp_factory=FakeSmtp,
    )
    sender.send_asset_flagged(
        event_id,
        {"assetId": "pump-1", "score": "12.00", "flaggedAt": "2026-10-29T00:00:00+00:00"},
    )

    assert messages[0]["Message-ID"] == f"<{event_id}@asset-health-worker>"
    assert "pump-1" in messages[0].get_content()
