"""The Decision Model: a prediction and its Lead Time become advice, or silence.

ADR 0003 sets the tiers and why they differ. A Watch at long range is optimised for
recall — missing a forming swell is worse than raising one that fades. A Go Call is
optimised for precision — acting on it costs the user a flight. They are deliberately
not one threshold with two names, because the two audiences have opposite tolerances for
being wrong.

Thresholds here are provisional. Ticket #12 fits them to Gold Days; until then the API
reports `calibrated: false` so nothing downstream can imply otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from nazarenow.models.base import Prediction

# Lead Time bands, in days from the day the forecast was fetched.
CONFIRMED_THROUGH = 1
GO_CALL_THROUGH = 7


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


def decide(prediction: Prediction, lead_time_days: int) -> Call:
    """Turn a prediction into a call at the given Lead Time.

    A call is withheld unless every condition of the rule holds. One failed condition is
    enough: a Go Call costs money, and a long-period swell arriving through onshore wind
    is not the day anyone flew for.
    """
    reasons = prediction.matched + prediction.unmatched

    if not prediction.matches_rule:
        status = Status.NONE
    elif lead_time_days <= CONFIRMED_THROUGH:
        status = Status.CONFIRMED
    elif lead_time_days <= GO_CALL_THROUGH:
        status = Status.GO
    else:
        status = Status.WATCH

    return Call(
        status=status,
        lead_time_days=lead_time_days,
        reasons=reasons,
        predicted_significant_wave_height=prediction.significant_wave_height,
    )
