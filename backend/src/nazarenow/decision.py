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

from nazarenow.models.base import Condition, Prediction

# Lead Time bands, in days from the day the call was issued.
CONFIRMED_THROUGH = 1
GO_CALL_THROUGH = 7

# A Watch does not require the wind condition. Wind direction a week or more out carries
# almost no information, and gating a Watch on it made the tier exactly as strict as a Go
# Call — one rule with two names, which is what ADR 0003 exists to prevent. What a Watch
# needs is a swell worth watching: size, period and direction.
#
# Named by identity. These were once the strings the Heuristic Baseline happens to print,
# matched as substrings against its failure messages: rewording a message moved days
# between tiers, and a model wording its failures differently made every day a Watch.
WATCH_CONDITIONS = (
    Condition.SIGNIFICANT_WAVE_HEIGHT,
    Condition.SWELL_PERIOD,
    Condition.SWELL_DIRECTION,
)


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

    A Go Call or a Confirmed statement requires every condition of the rule, wind
    included: a long-period swell arriving through onshore wind is not the day anyone
    flew for, and a Go Call costs money. A Watch requires only the swell conditions, so a
    building swell whose wind has not yet turned is still surfaced at range.

    Raises on a negative Lead Time. A call is issued *for* a date in the forecast, from
    the first day that forecast covers, so a date before its own issue date is a caller
    fault rather than a case to fall through. An earlier version returned silence here
    and described that as protecting users from a stale forecast presenting an elapsed Go
    Call as fresh advice — a branch nothing could reach, guarding against a danger it did
    not address.
    """
    if lead_time_days < 0:
        raise ValueError(
            f"lead time {lead_time_days} is negative: a call cannot be issued for a date "
            "before the forecast that produced it"
        )

    reasons = prediction.matched + prediction.unmatched

    if prediction.matches_rule and lead_time_days <= CONFIRMED_THROUGH:
        status = Status.CONFIRMED
    elif prediction.matches_rule and lead_time_days <= GO_CALL_THROUGH:
        status = Status.GO
    elif prediction.holds(*WATCH_CONDITIONS) and lead_time_days > CONFIRMED_THROUGH:
        status = Status.WATCH
    else:
        status = Status.NONE

    return Call(
        status=status,
        lead_time_days=lead_time_days,
        reasons=reasons,
        predicted_significant_wave_height=prediction.significant_wave_height,
    )
