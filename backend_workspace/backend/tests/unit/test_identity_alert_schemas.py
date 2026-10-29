"""Focused unit coverage for identity and maintenance-queue API schemas."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.alerts.schemas import MaintenanceQueueItem, MaintenanceQueuePage
from app.modules.identity.schemas import LoginRequest, TokenResponse, UserOut


def test_login_request_is_strict_and_trims_credential_fields() -> None:
    """Login accepts documented credentials but rejects blank and unknown input."""
    request = LoginRequest.model_validate(
        {"username": "  asset-manager  ", "password": "  correct-horse  "}
    )

    assert request.username == "asset-manager"
    assert request.password == "correct-horse"

    with pytest.raises(ValidationError):
        LoginRequest.model_validate({"username": "", "password": "password"})
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {"username": "asset-manager", "password": "password", "role": "asset_manager"}
        )


def test_token_response_serializes_only_the_public_contract() -> None:
    """Token responses use documented camelCase fields and omit credential material."""
    user_id = uuid.uuid4()
    response = TokenResponse(
        access_token="signed-token",
        expires_in=3600,
        user=UserOut(id=user_id, username="asset-manager", role="asset_manager"),
    )

    payload = response.model_dump(by_alias=True, mode="json")

    assert payload == {
        "accessToken": "signed-token",
        "tokenType": "Bearer",
        "expiresIn": 3600,
        "user": {
            "id": str(user_id),
            "username": "asset-manager",
            "role": "asset_manager",
        },
    }
    assert "password" not in payload


def test_maintenance_queue_serializes_camel_case_and_accepts_a_cursor() -> None:
    """Queue responses preserve the documented wire names and follow-up cursor."""
    alert_id = uuid.uuid4()
    page = MaintenanceQueuePage(
        items=[
            MaintenanceQueueItem(
                alert_id=alert_id,
                asset_id="PUMP-001",
                asset_type="Pump",
                location="North Yard",
                current_health_score=Decimal("39.50"),
                current_color_band="Red",
                flagged_since=dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc),
            )
        ],
        next_cursor="signed-next-page",
    )

    assert page.model_dump(by_alias=True, mode="json") == {
        "items": [
            {
                "alertId": str(alert_id),
                "assetId": "PUMP-001",
                "assetType": "Pump",
                "location": "North Yard",
                "currentHealthScore": "39.50",
                "currentColorBand": "Red",
                "flaggedSince": "2026-10-29T00:00:00Z",
            }
        ],
        "nextCursor": "signed-next-page",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "alertId": str(uuid.uuid4()),
            "assetId": "PUMP-001",
            "assetType": "Pump",
            "location": "North Yard",
            "currentHealthScore": "39.50",
            "currentColorBand": "Blue",
            "flaggedSince": "2026-10-29T00:00:00Z",
        },
        {
            "alertId": str(uuid.uuid4()),
            "assetId": "PUMP-001",
            "assetType": "Pump",
            "location": "North Yard",
            "currentHealthScore": "39.50",
            "currentColorBand": "Red",
            "flaggedSince": "2026-10-29T00:00:00Z",
            "unsupported": True,
        },
    ],
)
def test_maintenance_queue_rejects_invalid_colour_bands_and_unknown_fields(
    payload: dict[str, object],
) -> None:
    """Queue item validation keeps colour bands literal and response models strict."""
    with pytest.raises(ValidationError):
        MaintenanceQueueItem.model_validate(payload)
