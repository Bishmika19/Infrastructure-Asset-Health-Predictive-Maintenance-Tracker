"""Inspection form-schema validation tests (FR-3)."""

import pytest
from pydantic import ValidationError

from app.modules.inspections.schemas import InspectionCreate, MAX_PHOTO_BYTES, MAX_PHOTOS_PER_INSPECTION


def test_inspection_schema_uses_camel_case_and_trims_observations():
    """Inspection requests accept contract casing and normalize observations."""
    request = InspectionCreate.model_validate(
        {"conditionRating": "Fair", "observations": "  Visible surface wear  "}
    )
    assert request.condition_rating == "Fair"
    assert request.observations == "Visible surface wear"


@pytest.mark.parametrize(
    "payload",
    [
        {"conditionRating": "Unknown", "observations": "Valid"},
        {"conditionRating": "Good", "observations": "   "},
        {"conditionRating": "Good", "observations": "x" * 4001},
        {"conditionRating": "Good", "observations": "Valid", "unexpected": True},
    ],
)
def test_inspection_schema_rejects_invalid_fields(payload):
    """Invalid ratings, observations, and unknown fields are rejected before persistence."""
    with pytest.raises(ValidationError):
        InspectionCreate.model_validate(payload)


def test_photo_limit_constants_match_the_supported_contract():
    """The server keeps the OD-06 default photo count and decimal byte limit explicit."""
    assert MAX_PHOTOS_PER_INSPECTION == 10
    assert MAX_PHOTO_BYTES == 10_000_000
