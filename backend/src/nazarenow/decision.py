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
from typing import TYPE_CHECKING

from nazarenow.models.base import Condition, Prediction

if TYPE_CHECKING:  # `distribution` reaches the model layer, which would import back
    from nazarenow.distribution import PredictiveDistribution

# Lead Time bands, in days from the day the call was issued.
CONFIRMED_THROUGH = 1
GO_CALL_THROUGH = 7

GO_CALL_MINIMUM_HEIGHT_PROBABILITY = 0.70
"""How much of the incoming reading must clear the height bar for a Go Call (#15).

The same trade ADR 0003 makes for Model Spread, arrived at from a third direction: a day whose
height is not probable enough falls to a Watch — the swell is still worth watching, it is
simply not yet worth a flight.

**Named for the height bar, not for confidence (#76, ADR 0014).** The glossary assigns
"confidence" to Model Spread, which `decide()` reads as its own gate a line from this one and
which withholds a Go Call for a different reason. The floor follows the shipped bars' naming —
`go_call_minimum_swell_period_s`, `watch_minimum_swell_period_s` — rather than a shorter name
that would read as the probability itself instead of the floor under it.

**Priced against Gold Day recall, in ADR 0010's shape.** The strictest floor that refuses a
Go Call to no Gold Day the height condition admits. `analysis/forecast_error/height_probability.py`
runs the measurement: every Gold Day's own peak sea, restated into operational units, scored
against the shipped Forecast Error Profile at each Lead Time it could be called at. The
binding days are the two 3.04 m Gold Days, which bottom out at 0.72 at five days; 0.70 is the
step below that rather than a bar sitting exactly on them, for the reason `fit_height` gives
about the next Gold Day half a metre smaller.

**What that costs, and what the obvious value would have cost.** At this floor the rule
refuses a Go Call in the band between the height bar and the smallest Gold Day — 2.75 m to
about 3.0 m, where no Gold Day has ever been observed. A day reading exactly the bar is a coin
flip about clearing it, 0.52 at one day out, and that is the day this exists to stop somebody
booking. At 0.9 it would instead have taken the Go Call from **7 of the 37 Gold Days the
height bar admits**, which is a recall loss on precisely the days the system exists to call.

That 0.9 was believed inert, and the belief came from measuring the wrong quantity: the
probability was read off the model's amplified *output* against a bar that judges the
*incoming reading*, which flatters every marginal day by the gain. `PredictiveDistribution.
height_bar_probability` carries that correction and why it matters.

**The precision half is still unpriced, and that limitation is real.** ADR 0010 could price
the Watch bar in both directions because the Hindcast supplies outcomes; it contains no
forecast error, so how many *false* Go Calls this floor prevents cannot be scored the same
way. What is now measured is the half that can be: it costs no Gold Day.
"""

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
        "the independent wave models agree the hour behind this call clears the Go Call bar"
    ),
    Agreement.DIVIDED: (
        "the independent wave models do not agree the hour behind this call clears the Go "
        "Call bar, so this is a Watch rather than a Go Call"
    ),
    Agreement.UNMEASURED: (
        "too few independent wave models reported the hour behind this call to establish "
        "whether they agree, so a Go Call is withheld"
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
    model_agreement: Agreement
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

    plausible_range_m: tuple[float, float] | None = None
    """The 5th-to-95th percentile of the Predictive Distribution, in metres (#15).

    `None` when the call was decided without one, which is every caller scoring a Hindcast:
    what the ocean did carries no forecast to be uncertain about.
    """

    height_bar_probability: float | None = None
    """How much of the distribution clears the calibrated height bar.

    The height condition alone — not the swell period, swell direction or wind conditions that
    a Go Call also rests on. `PredictiveDistribution.height_bar_probability` records why the
    wider number is not available (#66).
    """

    uncertainty_measured: bool | None = None
    """Whether a measured Forecast Error Profile covered this Lead Time.

    `False` beyond the archive's seven days, where the width is extrapolated. Carried so the
    interface can be visibly more cautious rather than presenting an extrapolation as
    evidence, which is #15's sixth criterion.
    """

    go_call_withheld_for_uncertainty: bool = False
    """Whether the distribution, not the models, refused a Go Call.

    Deliberately separate from `go_call_withheld`. Both end in a Watch, and a reader deserves
    to know which happened: the forecasters disagreeing about a swell is a different fact
    about the world from one forecast being too uncertain to book on.
    """


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


_UNCERTAIN_REASON = "the forecast is too uncertain at this range to book on"


def _height_probable_enough(distribution: PredictiveDistribution | None) -> bool:
    """Whether a distribution supports a Go Call, and `True` when there is none.

    Two separate cases return `True` without consulting a probability, and both are
    deliberate. A caller scoring a Hindcast passes no distribution, because what the ocean
    did carries no forecast error; and a distribution built without the height bar cannot
    answer the question, so it does not get to veto on a number it never computed.
    """
    if distribution is None or distribution.height_bar_probability is None:
        return True
    return distribution.height_bar_probability >= GO_CALL_MINIMUM_HEIGHT_PROBABILITY


def decide(
    prediction: Prediction,
    lead_time_days: int,
    agreement: Agreement,
    distribution: PredictiveDistribution | None = None,
) -> Call:
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

    # The distribution's own refusal, kept apart from the models'. `probable` is True when
    # there is no distribution at all, because a Hindcast carries no forecast to be uncertain
    # about and scoring one must not silently become stricter than the rule it is scoring.
    #
    # Named for the height bar rather than for how sure the system is, because `agreement` on
    # the next line is Model Spread — the quantity the glossary assigns "confidence" to — and
    # the two gates produce different Watches on purpose (ADR 0014).
    probable = _height_probable_enough(distribution)
    uncertain = available and agreement is Agreement.AGREED and not probable

    reasons = prediction.matched + prediction.unmatched
    if available:
        reasons += (AGREEMENT_REASONS[agreement],)
    if uncertain:
        reasons += (_UNCERTAIN_REASON,)

    if prediction.holds(*GO_CONDITIONS) and lead_time_days <= CONFIRMED_THROUGH:
        status = Status.CONFIRMED
    elif available and agreement is Agreement.AGREED and probable:
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
        model_agreement=agreement,
        # What the distribution contributes, asked of the distribution (#67). Three
        # consecutive `None if distribution is None else distribution.X` lines meant this
        # function knew the spelling of every field a `PredictiveDistribution` hands a call,
        # and would have needed editing again for the fourth.
        #
        # Nothing at all when there is no distribution, rather than three explicit `None`s:
        # the fields already default to `None` on `Call`, and that default is the documented
        # state — a call decided without one. Spelling them here would restate the dataclass.
        **({} if distribution is None else distribution.as_call_fields()),
        go_call_withheld_for_uncertainty=uncertain,
    )
