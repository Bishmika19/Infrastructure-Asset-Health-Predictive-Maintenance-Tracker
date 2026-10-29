"""Asset-register schema validation tests (FR-1)."""

import datetime as dt

import pytest
from pydantic import ValidationError

from app.modules.assets.schemas import AssetCreate, AssetUpdate


def _payload(**overrides):
    return {
        "assetId": "PUMP-001",
        "assetType": "Pump",
        "location": "North Yard",
        "installationDate": "2020-01-01",
        "manufacturer": "Acme",
        "lastServiceDate": "2025-01-01",
        **overrides,
    }


def test_asset_create_uses_camel_case_and_rejects_unknown_fields():
    created = AssetCreate.model_validate(_payload(location="  North Yard  "))
    assert created.asset_id == "PUMP-001"
    assert created.location == "North Yard"
    with pytest.raises(ValidationError):
        AssetCreate.model_validate(_payload(extra="not allowed"))


@pytest.mark.parametrize(
    "payload",
    [
        _payload(assetType="Generator"),
        _payload(lastServiceDate="2019-12-31"),
        _payload(installationDate=(dt.date.today() + dt.timedelta(days=1)).isoformat()),
    ],
)
def test_asset_create_rejects_invalid_enum_and_dates(payload):
    with pytest.raises(ValidationError):
        AssetCreate.model_validate(payload)


def test_asset_update_requires_a_changed_field_and_preserves_explicit_null():
    with pytest.raises(ValidationError):
        AssetUpdate.model_validate({})
    update = AssetUpdate.model_validate({"lastServiceDate": None})
    assert update.model_dump(exclude_unset=True) == {"last_service_date": None}
