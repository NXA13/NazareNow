"""Model Spread: how much the independent wave models disagree about a date.

ADR 0003 makes this the system's uncertainty estimate. No ensemble marine forecast is
available to us, so several independent models are asked about the same date and their
disagreement is the doubt. Narrow spread means confidence; wide spread means doubt.

**Each organisation votes once.** Five model identifiers at Praia do Norte are three
organisations — EWAM and GWAM are both DWD, and the two GFS Wave resolutions are both NCEP.
Two resolutions of one centre's model share its physics, its assimilation and its bugs, so
counting them separately makes the ensemble look twice as corroborated as it is. That is the
concrete meaning of ADR 0003's word *independent*, and it is what keeps the number comparable
when one member stops answering at long Lead Time: DWD still has GWAM, so the vote count does
not move.

**This is an upper bound on disagreement, not a calibrated uncertainty.** The models publish
on different cycles and their runs are not aligned — run age cannot be read from the provider
at all (`analysis/model_spread/`). #8 measured what that costs: staleness accounts for about
6% of the spread at one day's Lead Time and up to 29% at six. It is safe to leave uncorrected
only because the error has a direction. Sampling two providers at different run ages can make
them look more different than they are but cannot hide genuine agreement, so the contamination
inflates the spread, and an inflated spread reads as more doubt. It errs toward caution and
never toward a Go Call that should not have been issued.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# The roster, mapped to the organisation that runs each model. ADR 0003 named four models
# including ECMWF WAM, which returns a null Swell partition here and is unusable whatever
# the quality of its wave model; `analysis/forecast_models/` carries the per-model evidence.
PROVIDERS = {
    "meteofrance_wave": "MeteoFrance",
    "dwd_ewam": "DWD",
    "dwd_gwam": "DWD",
    "ncep_gfswave025": "NCEP",
    "ncep_gfswave016": "NCEP",
}

ORGANISATIONS = sorted(set(PROVIDERS.values()))

MINIMUM_PROVIDERS = 2
"""Below this there is no disagreement to measure.

One opinion is not an ensemble, and a spread of zero from a single provider is not confidence
— it is silence wearing confidence's clothes. A date that cannot reach two organisations
carries no Model Spread at all rather than a reassuring number.
"""

BEARINGS = frozenset({"swell_direction", "wave_direction", "wind_direction"})
"""Readings measured in degrees around a circle rather than along a line.

Only `swell_direction` is a Model Spread variable today; the other two are named because this
set decides arithmetic and a bearing added to it later would otherwise be wrong by default.

Named rather than inferred from the unit, because the unit is the provider's string and this
decides arithmetic. Subtracting the smallest bearing from the largest is right for metres and
seconds and catastrophically wrong for degrees: two models agreeing on a north swell at 355°
and 5° are 10° apart, and the plain range calls them 350° apart. That reports near-total
disagreement on a day of near-perfect agreement — the inversion ADR 0003's uncertainty
estimate exists to prevent — and it lands hardest on northerly swell, which is what the
Nazaré Canyon focuses.
"""


def is_degraded(providers: Sequence[str]) -> bool:
    """Whether this many organisations is fewer than the full roster.

    One predicate, because the read path derives the flag rather than storing it (a stored
    flag and the list it describes can disagree after a roster change) and would otherwise
    restate the comparison beside a second copy of the roster's size. Two copies of "degraded
    means fewer than all of them" is exactly how the interface comes to say "2 of 3" while
    the backend knows about four.
    """
    return len(providers) < len(ORGANISATIONS)


@dataclass(frozen=True)
class Spread:
    """Disagreement on one variable at one moment, and who contributed to it.

    `providers` travels with the number because a spread computed from two organisations and
    one computed from three are not comparable, and nothing else in the record would say
    which happened. ADR 0003's uncertainty estimate degrades when a provider is unavailable;
    it must degrade *visibly*.

    `lowest` and `highest` travel with it for a different reason: the width alone is a bare
    number, and #8 asks for Model Spread in terms a reader can interpret. "The models put
    this day between 3.1 m and 4.5 m" is the same measurement said usefully.

    For a variable in `BEARINGS` these two are the *arc's* start and end, running clockwise
    from `lowest` to `highest`, so across north `highest` is the smaller number — 355° to 5°
    names the correct 10° arc and 5° to 355° would name the wrong 350° one.
    """

    variable: str
    value: float
    lowest: float
    highest: float
    providers: tuple[str, ...]
    models_reporting: int

    @property
    def degraded(self) -> bool:
        """Whether this rests on fewer organisations than the full roster."""
        return is_degraded(self.providers)


@dataclass(frozen=True)
class DaySpread:
    """One date's Model Spread, and how much of the date it was measured across.

    The two counts are not decoration. A day whose spread rests on two of its twenty-four
    hours is a different claim from one measured throughout, and `spread` alone cannot say
    which — the same reason `providers` travels on a `Spread`. A day the ensemble did not
    reach at all carries `spread=None` and is still recorded, because a missing date is
    indistinguishable from a Pipeline Run that never happened.
    """

    spread: Spread | None
    hours_measured: int
    hours_total: int


def by_provider(readings: dict[str, float], variable: str) -> dict[str, float]:
    """Collapse each organisation's models to one opinion: the median of what it ran.

    The median rather than the mean, so a single member returning an outlier cannot drag its
    organisation's vote. With two members the two are equivalent; with one it is that model.

    A bearing is collapsed to the centre of the arc its models span, because a plain median
    has the same circular fault the spread does — DWD's two models at 355° and 5° take a
    median of 180°, inventing a southerly swell out of two northerly forecasts and then
    widening the spread against everybody else. For one or two models the arc centre *is* the
    median; beyond two it is a midrange, and so more exposed to an outlier than the line above
    promises. No organisation on this roster runs more than two models, and the roster is
    twenty lines up — but adding a third would quietly change what an organisation's vote
    means for direction only.
    """
    grouped: dict[str, list[float]] = {}
    for model, value in readings.items():
        if model not in PROVIDERS:
            raise KeyError(
                f"{model!r} is not on the roster; a model whose organisation is unknown "
                "cannot be given a vote, and giving it one would silently change the "
                "ensemble's size"
            )
        grouped.setdefault(PROVIDERS[model], []).append(value)

    if variable in BEARINGS:
        return {provider: _arc_centre(values) for provider, values in grouped.items()}
    return {provider: statistics.median(values) for provider, values in grouped.items()}


def spread_of(values: list[float]) -> float:
    """Disagreement as the full range, not the standard deviation.

    With three opinions a standard deviation is computed on too few points to mean what its
    name implies, and it shrinks when one member is missing even if the survivors disagree
    exactly as much. The range says the plain thing: the most and least these forecasters
    think, and the gap between.
    """
    if len(values) < MINIMUM_PROVIDERS:
        raise ValueError("spread needs at least two opinions; one model is not an ensemble")
    return max(values) - min(values)


def arc_of(bearings: list[float]) -> tuple[float, float, float]:
    """The smallest arc containing every bearing: where it starts, where it ends, how wide.

    Found by locating the widest *empty* gap between neighbouring bearings and taking the
    rest of the circle. That is the only definition that gives the same answer wherever the
    provider happens to have put zero, which is the whole point.

    Duplicates are removed first. Left in, two identical bearings leave every gap at zero, the
    widest empty gap is nothing, and the arc comes out as the entire circle — maximum
    disagreement reported on exact agreement, which is the failure this function exists to
    prevent, reappearing at its own edge case.
    """
    ordered = sorted({bearing % 360 for bearing in bearings})
    if not ordered:
        raise ValueError("an arc needs at least one bearing")
    if len(ordered) == 1:
        return ordered[0], ordered[0], 0.0

    gaps = [(ordered[(i + 1) % len(ordered)] - ordered[i]) % 360 for i in range(len(ordered))]
    widest = max(range(len(gaps)), key=gaps.__getitem__)
    # The arc runs from the bearing just *after* the empty gap round to the one just before.
    return ordered[(widest + 1) % len(ordered)], ordered[widest], 360.0 - gaps[widest]


def _arc_centre(bearings: list[float]) -> float:
    start, _, width = arc_of(bearings)
    return (start + width / 2) % 360


def extent_of(variable: str, values: list[float]) -> tuple[float, float, float]:
    """The lowest opinion, the highest, and the distance between them, on the right geometry.

    One place decides whether a variable is a line or a circle, so a caller cannot get the
    endpoints from here and the width from somewhere else and have the two disagree.
    """
    if variable in BEARINGS:
        return arc_of(values)
    return min(values), max(values), spread_of(values)


def derive(variable: str, readings: dict[str, float | None]) -> Spread | None:
    """One variable's Model Spread from the models that reported, or `None` if too few did.

    `None` rather than zero, and rather than raising. A provider being unavailable degrades
    the uncertainty estimate rather than failing the Pipeline Run (ADR 0003), so this has to
    be an outcome the caller stores as "not measurable" — a zero here would be indistinguishable
    from perfect agreement and would read as maximum confidence at exactly the moment the
    system knows least.
    """
    reporting = {model: value for model, value in readings.items() if value is not None}
    if not reporting:
        return None
    opinions = by_provider(reporting, variable)
    if len(opinions) < MINIMUM_PROVIDERS:
        return None
    lowest, highest, width = extent_of(variable, list(opinions.values()))
    return Spread(
        variable=variable,
        value=width,
        lowest=lowest,
        highest=highest,
        providers=tuple(sorted(opinions)),
        models_reporting=len(reporting),
    )


def for_day(variable: str, hours: list[dict[str, float | None]]) -> DaySpread:
    """A date's Model Spread: the median hour's, taken from the hours that could be measured.

    **A real hour's real spread, not an average of several.** Averaging the widths and then
    taking the endpoints from somewhere else would produce a range whose ends do not bracket
    its own width — a figure no hour of the day actually reported. Choosing the median hour
    keeps the number, its endpoints and its list of contributing organisations describing one
    consistent moment, which is what makes it quotable.

    The median rather than the peak, so a single ragged hour does not become the day; and
    rather than the mean, for the reason `by_provider` gives. With an even number of hours it
    takes the wider of the two middles. That tiebreak errs toward doubt, which is the
    direction everything else here errs in: an overstated spread makes the system quieter, and
    a quiet system never issues a Go Call it should not have.

    ADR 0003 judges a *day* on its best matching hour, which is not this. **That is the hour
    the Go Call gate reads, and this is the hour the interface shows** — they are different
    hours on purpose. Identifying the first means running the Amplification Model, which is why
    per-model readings are stored per hour; `pipeline.agreement_at` computes it there, with no
    refetch and no migration. This one needs no model to find, so a reader is shown a figure
    the system can state plainly rather than one that presupposes its own prediction.

    The consequence is that a call and the spread displayed beside it describe different
    moments, and neither is recoverable from the other — which is why `day_call` records what
    the models said about its own hour rather than leaving a reader to infer it from this.
    """
    measured = [found for hour in hours if (found := derive(variable, hour)) is not None]
    if not measured:
        return DaySpread(spread=None, hours_measured=0, hours_total=len(hours))

    ordered = sorted(measured, key=lambda found: found.value)
    return DaySpread(
        spread=ordered[len(ordered) // 2],
        hours_measured=len(measured),
        hours_total=len(hours),
    )
