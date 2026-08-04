"""The Decision Model: a prediction and its Lead Time become advice, or silence.

ADR 0003 sets the tiers and why they differ. A Watch at long range is optimised for
**recall** — missing a forming swell is worse than raising one that fades. A Go Call is
optimised for **precision** — acting on it costs the user a flight. They are deliberately
not one threshold with two names, because the two audiences have opposite tolerances for
being wrong.

**A Go Call also requires the independent wave models to agree.** ADR 0003 has the tiers
driven by disagreement between them, #8 built that measurement, and its second half — this —
is what makes CONTEXT.md's Go Call entry true: issued only once Model Spread has narrowed.

The rule is about the *decision*, not the width. A Go Call needs the lowest organisation's
swell period to still clear the Go Call bar, so disagreement withholds a call exactly where it
reaches across the bar and nowhere else. Two models a full second apart, both well clear of
the bar, do not disagree about anything a traveller would act on.

That shape was chosen because every number in it is already measured. A rule of the more
obvious form — spread below some width in seconds — needs a number nothing in the record can
supply: per-model Swell readings have only been collected since #8's first half shipped, and
`analysis/model_spread/` is explicit that its one sample sits on a 0.4 m summer sea and must
not be believed. This rule reuses the bar #12 and #43 fitted to the Gold Days instead.

Three properties of the gate are deliberate and each is a way it could have gone wrong.

*It gates the Go Call and not the Confirmed statement.* Confirmed is issued a day out, to
users already travelling, and carries no booking recommendation — there is no flight to
withhold. It also could not degrade gracefully: a Watch requires a Lead Time beyond the
Confirmed band, so gating Confirmed would drop those days to silence rather than to a weaker
call, leaving somebody already at Praia do Norte told nothing at all.

*Absent is not narrow.* Fewer than two organisations reporting produces no Model Spread rather
than a spread of zero (`spread.derive`), and this treats that as a reason to withhold, never as
agreement. The inverse would issue the system's most confident calls exactly where it knows
least.

*Divided and unmeasured stay distinct*, though both withhold. "The models disagree about this
day" and "we could not reach enough models to ask" are different facts about a call, they read
differently to a user, and #11 scores calls against the inputs that were available when they
were issued.

Thresholds are no longer a gap either: ticket #12 fitted them to the Gold Days, they load from
data rather than code (`thresholds.py`), and the API reports `calibrated` from the fit's own
provenance rather than from an assertion.
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

# A Go Call and a Confirmed statement require wind, and a *longer* swell period than a
# Watch — the same measurement judged against the stricter of the two calibrated bars.
#
# That second requirement is what ticket #12 added, and it is what finally makes the tiers
# trade differently. Before it, a Watch and a Go Call differed only by the wind condition,
# and #11's backtest measured the consequence: across four seasons the two tiers caught
# exactly the same three Gold Days, because wind was never what blocked a Gold Day. Period
# always was. A recall tier that surfaces nothing the precision tier misses is one rule
# with two names, which is the outcome ADR 0003 exists to prevent.
#
# Named explicitly rather than read off `Prediction.matches_rule`, which asks only whether
# every condition a model *chose to judge* held. A model that never judges wind satisfies
# that on any clean swell and earns a Go Call through onshore wind — the same collapse from
# the other direction. Fixing the Watch tier to name its conditions and leaving these two
# reading `matches_rule` reproduced the defect one branch lower.
GO_CONDITIONS = (*WATCH_CONDITIONS, Condition.SWELL_PERIOD_FOR_GO_CALL, Condition.WIND)


class Status(StrEnum):
    CONFIRMED = "confirmed"
    GO = "go"
    WATCH = "watch"
    NONE = "none"


class Agreement(StrEnum):
    """What the independent wave models said about the hour a call rests on.

    Three outcomes rather than a boolean, because the two that withhold a Go Call withhold it
    for different reasons and a reader is owed which. A boolean would also have to pick one of
    them as its `False`, and whichever it picked, the other would arrive wearing that name.
    """

    AGREED = "agreed"
    """Every organisation's swell period for this hour clears the Go Call bar."""

    DIVIDED = "divided"
    """At least one organisation puts this hour under the bar. The models disagree about the
    decision itself, not merely about the sea."""

    UNMEASURED = "unmeasured"
    """Too few organisations reported this hour for there to be an agreement to establish.

    Never read as agreement. `spread.derive` returns no spread below two organisations rather
    than a spread of zero, for the reason this restates on the deciding side."""


# What the ensemble's verdict adds to the reasons a user reads, when it bore on the call.
#
# No number and no threshold in any of them. The bar is the Amplification Model's to name —
# it already prints "swell period 13.4s is at or above the 12.9s a Go Call needs" beside
# these — and a second copy here would be a threshold this module does not load and cannot
# keep in step.
AGREEMENT_REASONS = {
    Agreement.AGREED: (
        "the independent wave models agree this day's swell period clears the Go Call bar"
    ),
    Agreement.DIVIDED: (
        "the independent wave models do not agree this day's swell period clears the Go Call "
        "bar, so this is a Watch rather than a Go Call"
    ),
    Agreement.UNMEASURED: (
        "too few independent wave models reported this day to establish whether they agree, "
        "so a Go Call is withheld"
    ),
}


def agreement_of(pessimistic: Prediction | None) -> Agreement:
    """Read the ensemble's verdict off the gloomiest member's own prediction.

    The caller re-runs the Amplification Model over the deciding hour with the *lowest*
    organisation's swell period substituted, and hands the result here. That indirection is
    what keeps this module free of thresholds: whether a period clears the Go Call bar is a
    question only the model's calibrated numbers can answer, and asking it this way means the
    gate moves with a recalibration instead of drifting from one.

    `None` for an hour that could not be measured — fewer than two organisations reported —
    which is `spread.derive`'s own answer carried through rather than reinterpreted.
    """
    if pessimistic is None:
        return Agreement.UNMEASURED
    if pessimistic.holds(Condition.SWELL_PERIOD_FOR_GO_CALL):
        return Agreement.AGREED
    return Agreement.DIVIDED


# How much a call says, strongest first. A day is called at the best call any of its hours
# supports, so this orders them.
_STRENGTH = {Status.CONFIRMED: 3, Status.GO: 2, Status.WATCH: 1, Status.NONE: 0}


def strength(status: Status) -> int:
    """How strong a call this status is, for choosing between calls about the same day.

    Confirmed and Go differ only by Lead Time, which is fixed for a given day, so within one
    day the ordering is really "matched every condition" above "matched the swell" above
    "matched neither".
    """
    return _STRENGTH[status]


@dataclass(frozen=True)
class Call:
    status: Status
    lead_time_days: int
    reasons: tuple[str, ...]
    predicted_significant_wave_height: float
    agreement: Agreement
    """What the models said about the hour this call rests on, carried with the call.

    Recorded rather than re-derived, and it genuinely cannot be re-derived: `day_spread`
    stores the date's *median* hour, while a call is decided on its best matching hour, and
    those are different hours. Without this field the record would hold a call and a spread
    that describe two different moments of the same day, and nothing would say so.
    """

    go_call_withheld: bool
    """Whether the models refused a Go Call this day's conditions otherwise supported.

    Not derivable from `agreement` and `status` together, which is why it is here. A day whose
    own swell period sits below the Go Call bar has every organisation below it too, so it
    reports `DIVIDED` while the ensemble decided nothing — the disagreement is an arithmetic
    consequence of the day being small. Only this module knows whether the verdict changed
    anything, because only this module saw the conditions beside it.

    A reader scanning day cards sees two Watches, and one of them is a swell the system
    believes in and the forecasters have not settled on. That is the difference worth showing.
    """

    unit: str = "m"


def conditions_behind(status: Status) -> tuple[Condition, ...]:
    """The conditions a call of this status actually rests on.

    A Watch rests on the swell alone, so counting how many of a day's hours cleared *every*
    condition described something the Watch was never judged against: a real Watch day
    displayed "0 of 24 forecast hours match every condition" beside its own badge, which is
    arithmetically true and, as an explanation of that call, nonsense.
    """
    return WATCH_CONDITIONS if status is Status.WATCH else GO_CONDITIONS


def go_call_is_available(prediction: Prediction, lead_time_days: int) -> bool:
    """Whether everything except the models' agreement supports a Go Call.

    Named because two things need the same question and would otherwise ask it in two
    slightly different ways: the tier branch below, and the decision about whether the
    ensemble's verdict is worth telling the user. Reporting what the models thought about a
    flat summer Tuesday would bury the reason that mattered under one that never applied.
    """
    return (
        prediction.holds(*GO_CONDITIONS) and CONFIRMED_THROUGH < lead_time_days <= GO_CALL_THROUGH
    )


def decide(prediction: Prediction, lead_time_days: int, agreement: Agreement) -> Call:
    """Turn a prediction into a call at the given Lead Time, given what the models said.

    A Go Call or a Confirmed statement requires every condition of the rule: wind, because
    a long-period swell arriving through onshore wind is not the day anyone flew for, and
    the longer of the two calibrated swell periods, because a Go Call costs money. A Watch
    requires only the swell conditions at the looser period bar, so a building swell whose
    wind has not yet turned — or whose period is long enough to be worth watching without
    yet being long enough to book on — is still surfaced at range.

    A Go Call requires one thing more: `Agreement.AGREED`, meaning every organisation's swell
    period for this hour clears the Go Call bar. A day the models divide over falls to a
    Watch — the swell is still worth watching, it is simply not yet worth a flight — which is
    the same trade ADR 0003 makes for wind, arrived at from the other direction.

    `agreement` is required rather than defaulted, and that is the point of it. A default
    would let a caller take a Go Call from this function without ever consulting the models,
    which is precisely the state #8's second half exists to end; the two callers in
    `analysis/` that score the rule against a Hindcast have to say in their own source that
    they are assuming agreement, because a Hindcast is what the ocean did and contains no
    forecast to disagree.

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

    available = go_call_is_available(prediction, lead_time_days)
    withheld = available and agreement is not Agreement.AGREED

    reasons = prediction.matched + prediction.unmatched
    if available:
        reasons += (AGREEMENT_REASONS[agreement],)

    if prediction.holds(*GO_CONDITIONS) and lead_time_days <= CONFIRMED_THROUGH:
        status = Status.CONFIRMED
    elif available and agreement is Agreement.AGREED:
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
        go_call_withheld=withheld,
        agreement=agreement,
    )
