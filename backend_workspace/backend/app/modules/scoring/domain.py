"""Pure health-score rules (DEC-03, A-5, A-8, A-23). No I/O and no framework imports.

``Score = 100 - 100 x (0.20 x age + 0.30 x service + 0.50 x severity)`` where each
factor is clamped to 0..1. Rounding (OD-06 default) is half-up to two decimals and
the band is taken from the rounded score, so 39.99 is Red and 40.00 is Amber.
Change the constants here, and bump ``FORMULA_VERSION``, to alter the model.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

FORMULA_VERSION = "A5-v1"

EXPECTED_LIFE_YEARS = Decimal(20)
SERVICE_INTERVAL_DAYS = Decimal(365)
DAYS_PER_YEAR = Decimal("365.25")
WEIGHT_AGE = Decimal("0.20")
WEIGHT_SERVICE = Decimal("0.30")
WEIGHT_INSPECTION = Decimal("0.50")
SCORE_QUANTUM = Decimal("0.01")

GREEN_MIN = Decimal(70)
ALERT_THRESHOLD = Decimal(40)

BAND_GREEN = "Green"
BAND_AMBER = "Amber"
BAND_RED = "Red"

# A-8: condition rating -> inspection severity. No inspection counts as Excellent (A-23).
SEVERITY_BY_RATING: Dict[str, Decimal] = {
    "Excellent": Decimal("0"),
    "Good": Decimal("0.25"),
    "Fair": Decimal("0.5"),
    "Poor": Decimal("0.75"),
    "Critical": Decimal("1"),
}
CONDITION_RATINGS = tuple(SEVERITY_BY_RATING)

TRIGGER_ASSET_CREATE = "asset_create"
TRIGGER_INSPECTION = "inspection"
TRIGGER_SERVICE_UPDATE = "service_update"
TRIGGER_ASSET_UPDATE = "asset_update"
TRIGGER_NIGHTLY = "nightly"


@dataclass(frozen=True)
class ScoreInputs:
    """Validated inputs of one calculation."""

    installation_date: dt.date
    last_service_date: Optional[dt.date]
    latest_rating: Optional[str]
    calculated_on: dt.date


@dataclass(frozen=True)
class ScoreResult:
    """Rounded score, band and the reproducible inputs/factors."""

    score: Decimal
    band: str
    inputs: Dict[str, Any]


def _clamp01(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), value))


# PUBLIC_INTERFACE
def band_for(score: Decimal) -> str:
    """Return the colour band for an already-rounded score (70/40 thresholds)."""
    if score >= GREEN_MIN:
        return BAND_GREEN
    if score >= ALERT_THRESHOLD:
        return BAND_AMBER
    return BAND_RED


# PUBLIC_INTERFACE
def is_flag_score(score: Decimal) -> bool:
    """True when the score is below the alert threshold (a flag episode must be open)."""
    return score < ALERT_THRESHOLD


# PUBLIC_INTERFACE
def compute_score(inputs: ScoreInputs) -> ScoreResult:
    """Compute the A-5 health score for ``inputs``.

    Raises:
        ValueError: ``latest_rating`` is not one of the five A-8 ratings.
    """
    if inputs.latest_rating is not None and inputs.latest_rating not in SEVERITY_BY_RATING:
        raise ValueError(f"unknown condition rating: {inputs.latest_rating}")
    age_days = max(0, (inputs.calculated_on - inputs.installation_date).days)
    age_years = Decimal(age_days) / DAYS_PER_YEAR
    service_basis = inputs.last_service_date or inputs.installation_date
    service_days = max(0, (inputs.calculated_on - service_basis).days)
    severity = SEVERITY_BY_RATING[inputs.latest_rating] if inputs.latest_rating else Decimal(0)

    norm_age = _clamp01(age_years / EXPECTED_LIFE_YEARS)
    norm_service = _clamp01(Decimal(service_days) / SERVICE_INTERVAL_DAYS)
    penalty = Decimal(100) * (
        WEIGHT_AGE * norm_age + WEIGHT_SERVICE * norm_service + WEIGHT_INSPECTION * severity
    )
    score = (Decimal(100) - penalty).quantize(SCORE_QUANTUM, rounding=ROUND_HALF_UP)
    score = max(Decimal(0), min(Decimal(100), score))
    provenance: Dict[str, Any] = {
        "calculationDate": inputs.calculated_on.isoformat(),
        "installationDate": inputs.installation_date.isoformat(),
        "lastServiceDate": inputs.last_service_date.isoformat() if inputs.last_service_date else None,
        "serviceDateBasis": "last_service" if inputs.last_service_date else "installation_proxy",
        "ageYears": str(age_years.quantize(Decimal("0.0001"))),
        "normalizedAge": str(norm_age.quantize(Decimal("0.0001"))),
        "daysSinceService": service_days,
        "normalizedDaysSinceService": str(norm_service.quantize(Decimal("0.0001"))),
        "inspectionRating": inputs.latest_rating,
        "inspectionBasis": "latest_inspection" if inputs.latest_rating else "none_logged_default_excellent",
        "inspectionSeverity": str(severity),
    }
    return ScoreResult(score=score, band=band_for(score), inputs=provenance)
