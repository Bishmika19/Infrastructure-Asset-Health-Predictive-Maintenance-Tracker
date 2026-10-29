"""Focused pure-unit coverage for the A-5 scoring rules."""

import datetime as dt
from decimal import Decimal

import pytest

from app.modules.scoring.domain import (
    BAND_AMBER,
    BAND_GREEN,
    BAND_RED,
    ScoreInputs,
    band_for,
    compute_score,
)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (Decimal("39.99"), BAND_RED),
        (Decimal("40.00"), BAND_AMBER),
        (Decimal("69.99"), BAND_AMBER),
        (Decimal("70.00"), BAND_GREEN),
    ],
)
def test_score_band_boundaries(score, expected):
    assert band_for(score) == expected


def test_score_clamps_age_and_service_and_records_no_inspection_default():
    result = compute_score(
        ScoreInputs(
            installation_date=dt.date(1900, 1, 1),
            last_service_date=dt.date(1900, 1, 1),
            latest_rating=None,
            calculated_on=dt.date(2026, 1, 1),
        )
    )

    assert result.score == Decimal("50.00")
    assert result.band == BAND_AMBER
    assert result.inputs["normalizedAge"] == "1.0000"
    assert result.inputs["normalizedDaysSinceService"] == "1.0000"
    assert result.inputs["inspectionBasis"] == "none_logged_default_excellent"


def test_critical_inspection_applies_the_configured_fifty_point_penalty():
    result = compute_score(
        ScoreInputs(
            installation_date=dt.date(2026, 1, 1),
            last_service_date=dt.date(2026, 1, 1),
            latest_rating="Critical",
            calculated_on=dt.date(2026, 1, 1),
        )
    )

    assert result.score == Decimal("50.00")
    assert result.band == BAND_AMBER
