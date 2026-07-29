"""The Decision Model: a prediction and its Lead Time become advice, or silence.

ADR 0003 sets the tiers and why they differ. A Watch at long range is optimised for
**recall** — missing a forming swell is worse than raising one that fades. A Go Call is
optimised for **precision** — acting on it costs the user a flight. They are deliberately
not one threshold with two names, because the two audiences have opposite tolerances for
being wrong.

Two gaps are open here and are surfaced rather than papered over:

*Model Spread does not yet exist.* ADR 0003 has the tiers driven by disagreement between
independent wave models, which ticket #8 introduces. Until then tiers are decided by Lead
Time alone, and nothing in this system may claim a forecast has "converged" — there is no
measurement behind such a claim.

*Thresholds are uncalibrated.* Ticket #12 fits them to Gold Days. Until then they are the
surf community's rule of thumb and the API reports `calibrated: false`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from nazarenow.models.base import Prediction

# Lead Time bands, in days from the day the call was issued.
CONFIRMED_THROUGH = 1
GO_CALL_THROUGH = 7

# A Watch does not require the wind condition. Wind direction a week or more out carries
# almost no information, and gating a Watch on it made the tier exactly as strict as a Go
# Call — one rule with two names, which is what ADR 0003 exists to prevent. What a Watch
# needs is a swell worth watching: size, period and direction.
WATCH_CONDITIONS = ("significant wave height", "swell period", "swell direction")


class Status(StrEnum):
    CONFIRMED = "confirmed"
    GO = "go"
    WATCH = "watch"
    NONE = "none"


@dataclass(frozen=True)
class Call:
    status: Status
    lead_time_days: int
    reasons: tuple[str, ...]
    predicted_significant_wave_height: float
    unit: str = "m"


def _swell_conditions_hold(prediction: Prediction) -> bool:
    """Whether the swell itself is worth watching, ignoring the wind."""
    return not any(
        condition in failure for failure in prediction.unmatched for condition in WATCH_CONDITIONS
    )


def decide(prediction: Prediction, lead_time_days: int) -> Call:
    """Turn a prediction into a call at the given Lead Time.

    A Go Call or a Confirmed statement requires every condition of the rule, wind
    included: a long-period swell arriving through onshore wind is not the day anyone
    flew for, and a Go Call costs money. A Watch requires only the swell conditions, so a
    building swell whose wind has not yet turned is still surfaced at range.
    """
    reasons = prediction.matched + prediction.unmatched

    if lead_time_days < 0:
        # A call for a date already past. Storing calls with their issue date makes this
        # reachable when a stale forecast is served, and silence is the honest answer.
        status = Status.NONE
    elif prediction.matches_rule and lead_time_days <= CONFIRMED_THROUGH:
        status = Status.CONFIRMED
    elif prediction.matches_rule and lead_time_days <= GO_CALL_THROUGH:
        status = Status.GO
    elif _swell_conditions_hold(prediction) and lead_time_days > CONFIRMED_THROUGH:
        status = Status.WATCH
    else:
        status = Status.NONE

    return Call(
        status=status,
        lead_time_days=lead_time_days,
        reasons=reasons,
        predicted_significant_wave_height=prediction.significant_wave_height,
    )
