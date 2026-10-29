"""Focused unit coverage for the asset-history response schemas."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from app.modules.history.schemas import AssetHistoryEvent


def test_history_event_serializes_camel_case_fields() -> None:
    """Timeline events expose the documented camelCase wire representation."""
    event_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    event = AssetHistoryEvent(
        event_id=event_id,
        event_kind="work_order_status_changed",
        occurred_at=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc),
        actor_id=actor_id,
        details={"previousStatus": "Open", "newStatus": "Assigned"},
    )

    assert event.model_dump(by_alias=True, mode="json") == {
        "eventId": str(event_id),
        "eventKind": "work_order_status_changed",
        "occurredAt": "2026-10-29T00:00:00Z",
        "actorId": str(actor_id),
        "details": {"previousStatus": "Open", "newStatus": "Assigned"},
    }


def test_history_event_rejects_unknown_kind_and_fields() -> None:
    """The timeline schema rejects invented event kinds and output fields."""
    with pytest.raises(ValidationError):
        AssetHistoryEvent(
            event_id=uuid.uuid4(),
            event_kind="score_recalculated",
            occurred_at=dt.datetime.now(dt.timezone.utc),
            details={},
        )

    with pytest.raises(ValidationError):
        AssetHistoryEvent(
            event_id=uuid.uuid4(),
            event_kind="alert_opened",
            occurred_at=dt.datetime.now(dt.timezone.utc),
            details={},
            unsupported=True,
        )
