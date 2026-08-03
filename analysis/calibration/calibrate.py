"""Fitting the Decision Model's thresholds to the Gold Days, and validating them held out.

Ticket #12. #11 established the benchmark and found what was wrong with it; this chooses
the numbers, writes them where the running system reads them, and reports what they score
on years the fit never saw.

**The real rule, not a copy.** `HeuristicBaseline` and `decide` are imported from the
running system and driven with candidate thresholds. A reimplementation here would drift
from the thing it calibrates, and the drift would ship.

**Only swell period is fitted per tier.** Period is the one condition the evidence can
distinguish, and so the only place ADR 0003's recall tier and precision tier can genuinely
differ. Height and the two arcs are checked rather than fitted: fitting an arc to a couple
of dozen Gold Days would narrow it onto noise while changing no call, so
`verify_shared_conditions` checks they admit every Gold Day and reports the margin instead,
which is the honest version of the same claim.

**The light-wind exemption is fitted too, but once rather than per tier.** #11 read height,
direction and wind as blocking no Gold Day, on the 9 Gold Days the Swell record then
reached. #39's ingestion disproved that for wind — six of the 25 fitting Gold Days were
blocked by the offshore arc on breezes of 4-16 km/h — and ADR 0009 answered it with
`light_wind_exemption_kmh`, which `fit_light_wind_exemption` fits here. It is shared by both
tiers, so it is fitted before the period sweep rather than inside it.

**Chronological split.** Fitted on the earlier Big-Wave Seasons, validated on the later ones
— the direction the system runs in: fit on the past, apply to the future.

**Fitted on the reanalysis, shipped in operational units.** #39 replaced the source with the
Copernicus reanalysis, which is what takes this from 9 Gold Days to 38. The fit runs in the
reanalysis's own units, because a fit is only meaningful if it is internally consistent. But
`thresholds.json` is read by the live Pipeline Run, which consumes Open-Meteo and never sees
a reanalysis — and `analysis/overlap/README.md` measured that the same sea reads about half a
second longer in the reanalysis. So the three fitted wave bars are translated back into
operational units on the way out, and the translation is recorded in the file beside them.
The light-wind exemption is deliberately not translated: wind reaches both sides of that
boundary from ERA5, so it is already in the units it is applied in.
Shipping the untranslated numbers would have made the deployed system quietly stricter than
the fit intended, which is the mirror image of the mistake #39 was written to prevent.

Run:
    .venv/Scripts/python.exe analysis/calibration/calibrate.py
    .venv/Scripts/python.exe analysis/calibration/calibrate.py --check
"""

from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

sys.path.insert(0, str(ROOT / "analysis" / "backtest"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

sys.path.insert(0, str(ROOT / "analysis" / "overlap"))

import backtest  # noqa: E402
import measure  # noqa: E402
from backtest import GoldDay, load_gold_days, reanalysis_hours, season_of  # noqa: E402
from nazarenow.days import group_by_date  # noqa: E402
from nazarenow.decision import Status, decide, strength  # noqa: E402
from nazarenow.models.heuristic import HeuristicBaseline, _within  # noqa: E402
from nazarenow.thresholds import DEFAULT_PATH, Thresholds, parse  # noqa: E402

LEAD_TIME_DAYS = backtest.LEAD_TIME_DAYS
GO_TIERS = backtest.GO_TIERS
WATCH_OR_BETTER = backtest.WATCH_OR_BETTER

FIT_SEASONS = (
    "2011/12",
    "2012/13",
    "2013/14",
    "2014/15",
    "2015/16",
    "2016/17",
    "2017/18",
    "2018/19",
    "2019/20",
)
TEST_SEASONS = ("2020/21", "2021/22", "2022/23", "2023/24", "2024/25", "2025/26")
FIT_SPAN = "2011/12-2019/20"
TEST_SPAN = "2020/21-2025/26"

"""Split on Big-Wave Season boundaries, not calendar years.

**Reallocated for #39.** The record used to start in 2022, because that is where the Swell
partition started; the reanalysis carries it back to 2011, and the splits move with it. The
fit now sees **25** Gold Days and the held-out split **13**, where before it was 6 and 3.
The old held-out set was "far too few to be reassuring" and said so; 13 is still small and
is still worth saying, but it is a different order of claim.

The boundary sits after 2019/20 for two reasons. It is roughly two-thirds of the Gold Days,
and it puts every one of the 7 pre-SAR Gold Days — the ones before Sentinel-1 spectra began
constraining the swell partitions in March 2016 — inside the **fitting** split. The held-out
evaluation is then run entirely on the homogeneous part of the record, which is the half of
the split that has to carry a claim.

Note that 2022/23 contributes no Gold Days at all: no Nazaré contest ran and the Big Wave
Awards did not hold an edition. It is a real season in the denominator with nothing in the
numerator, which is why `Split.seasons` counts seasons appearing in the record rather than
Gold Days.

CONTEXT.md: a Big-Wave Season runs October through March, "a season is never a calendar
year, and splitting one across two years destroys the unit that matters." An earlier version
of this file split on the calendar — 2022-2023 to fit, 2024-2025 to test — which cut the
**2023/24 season in half**: its October-to-December went to the fitting split and its
January-to-March to the held-out one. Two things followed, and neither was visible in the
report.

The held-out split stopped being held out. A season is one weather pattern, and the fit had
seen three months of the season a held-out Gold Day sits in.

And `Split.seasons` counted 2023/24 in *both* halves, so the two splits reported three
seasons each out of five that exist. That denominator is what turns a Go Call count into
`per_season`, which is the constraint `choose_go_bar` fits against — so the season the split
double-counted made the rule look more restrained than it was.

The allocation of Gold Days is unchanged by the fix: all six fitting Gold Days fall in
2021/22, and the three held-out ones in 2023/24, 2024/25 and 2025/26. Only the boundary
moved.
"""

PERIOD_SWEEP = tuple(round(10.0 + 0.5 * step, 1) for step in range(13))
"""10.0s to 16.0s in half-second steps.

Half a second is about the resolution the question supports: #11's reconstruction carried
an RMSE of 1.04s, and the operational feed reports period to one decimal. Sweeping finer
would choose between candidates the data cannot tell apart.
"""

GO_CALLS_PER_SEASON_BUDGET = 8.0
"""The stated precision target, expressed as a rate rather than a precision.

Precision against Gold Days is only a lower bound — a flagged day that nobody photographed
is not thereby a false positive (#11, and ADR 0006 on how accuracy must be reported). So
optimising a precision *number* would optimise against who happened to be holding a camera.

What can be stated honestly is what a Go Call costs the person receiving it. It says book
travel to Portugal. Eight per Big-Wave Season is roughly one every three weeks — frequent
enough to be worth subscribing to, rare enough that acting on one is a decision rather than
a routine. That is a product judgement, written down here as one, and it is the only
hand-chosen number left in the calibration.
"""

HEIGHT_STEP_M = 0.25
"""Height bars are floored to this, so the fitted value is a number a person would choose."""

LIGHT_WIND_STEP_KMH = 0.5
"""The light-wind exemption is rounded **up** to this, not down.

The opposite direction from `HEIGHT_STEP_M`, because the two bars point opposite ways: a
lower height bar is more permissive, and a *higher* exemption is. Rounding the exemption down
would put it just under the calmest hour of the Gold Day that set it and drop that day
straight back out of the fit.
"""


@dataclass(frozen=True)
class Split:
    """One half of the chronological split, and the Gold Days inside it."""

    name: str
    span: str
    hours: list[dict[str, float | str]]
    gold: dict[str, GoldDay]

    @property
    def seasons(self) -> float:
        """Big-Wave Seasons covered, for turning a Go Call count into a rate.

        Counted as distinct seasons appearing in the record rather than as elapsed years,
        because the record starts and ends mid-season and a season is the unit a reader
        thinks in (CONTEXT.md).
        """
        return float(len({season_of(str(hour["at"])[:10]) for hour in self.hours}))


@dataclass(frozen=True)
class Score:
    """What one threshold set does to one split."""

    gold_called: int
    gold_total: int
    flagged: int
    flagged_that_are_gold: int
    seasons: float

    @property
    def recall(self) -> float:
        return self.gold_called / self.gold_total if self.gold_total else 0.0

    @property
    def precision_lower_bound(self) -> float:
        return self.flagged_that_are_gold / self.flagged if self.flagged else 0.0

    @property
    def per_season(self) -> float:
        return self.flagged / self.seasons if self.seasons else 0.0


def call_days(hours: list[dict[str, float | str]], model: HeuristicBaseline) -> dict[str, Status]:
    """The strongest call each Nazaré local day supports, under one threshold set.

    Mirrors how the Pipeline Run reduces a day — every hour decided on its own, the
    strongest call winning — and imports `strength` rather than reimplementing the ordering.
    """
    calls: dict[str, Status] = {}
    for day, day_hours in group_by_date(hours).items():
        best = Status.NONE
        for hour in day_hours:
            readings = {k: v for k, v in hour.items() if k != "at"}
            call = decide(model.predict(readings), LEAD_TIME_DAYS)
            if strength(call.status) > strength(best):
                best = call.status
        calls[day] = best
    return calls


def score(split: Split, thresholds: Thresholds, tiers: tuple[Status, ...]) -> Score:
    calls = call_days(split.hours, HeuristicBaseline(thresholds))
    in_span = [d for d in split.gold if d in calls]
    flagged = [d for d, status in calls.items() if status in tiers]
    return Score(
        gold_called=sum(1 for d in in_span if calls[d] in tiers),
        gold_total=len(in_span),
        flagged=len(flagged),
        flagged_that_are_gold=sum(1 for d in flagged if d in split.gold),
        seasons=split.seasons,
    )


UNFITTED = parse(
    {
        # The conditions this calibration does not fit, at the surf community's values.
        # Stated here rather than read from the shipped file, which this script *writes* —
        # loading it would make each run start from the last run's output, so a fit could
        # walk away from these values one run at a time with nothing recording that it had.
        "swell_arc": [255.0, 330.0],
        "offshore_wind_arc": [20.0, 180.0],
        "maximum_wind_speed_kmh": 35.0,
        # Placeholders. Every candidate replaces all four; `parse` will not accept a set
        # without them, and a set that could omit one would silently inherit whatever these
        # said.
        "minimum_significant_wave_height_m": 3.0,
        "watch_minimum_swell_period_s": 12.0,
        "go_call_minimum_swell_period_s": 13.0,
        "light_wind_exemption_kmh": 1.0,
        "calibration": None,
    }
)
"""The starting point every candidate varies from. See `verify_shared_conditions`."""


BUOY_MEASURED = "buoy_measured"
"""The strongest evidence class in `gold_days.jsonl`: a day with an instrument behind it.

`gold_days/` records how each Gold Day is known — 7 buoy-measured, 7 hindcast-only, 24
unknown across the whole list. #12's brief asks for this subset to be reported separately,
because a day whose size was measured is a different quality of label from one attested by a
photograph, and a recall figure that mixes them cannot be checked against either.
"""


def buoy_measured_recall(
    split: Split, thresholds: Thresholds, tiers: tuple[Status, ...]
) -> tuple[int, int]:
    """Gold Days called, counting only those with a buoy measurement behind them.

    Recall only. A precision figure restricted to this subset would be meaningless — it
    would count every flagged day without an instrument as a miss, including the other Gold
    Days.
    """
    calls = call_days(split.hours, HeuristicBaseline(thresholds))
    measured = [
        date
        for date, gold in split.gold.items()
        if date in calls and gold.evidence_class == BUOY_MEASURED
    ]
    return sum(1 for date in measured if calls[date] in tiers), len(measured)


def candidate(
    watch_period: float,
    go_period: float,
    height: float,
    light_wind: float = LIGHT_WIND_STEP_KMH,
) -> Thresholds:
    """A threshold set to try, built through the same parser the running system uses.

    Going through `parse` rather than constructing `Thresholds` directly means a candidate
    the deployed system would refuse to load can never be scored here and recommended.

    `light_wind` must be the **fitted** exemption everywhere the sweep is scored. The Go bar
    is chosen against a Go Calls-per-season budget, and the exemption changes which days
    produce a Go Call — so a sweep run under a different exemption would fit the period bar
    to a rule that is not the one shipping. The default exists only for `check`, which drives
    the choosers with synthetic rows and never touches wind.

    There is no circularity in fitting the exemption first: it is determined entirely by the
    wind on Gold Days and does not depend on any period bar.
    """
    return UNFITTED.replacing(
        minimum_significant_wave_height_m=height,
        watch_minimum_swell_period_s=watch_period,
        go_call_minimum_swell_period_s=go_period,
        light_wind_exemption_kmh=light_wind,
    )


def fit_height(split: Split) -> tuple[float, float]:
    """The tightest height bar admitting every Gold Day in the fitting split.

    Returns the bar and the smallest peak it had to admit, so the report can show how much
    room is left. Floored to `HEIGHT_STEP_M` rather than set exactly at the smallest peak:
    a bar sitting precisely on the smallest Gold Day in six is fitted to that one day, and
    the next Gold Day half a metre smaller would fall straight through it.
    """
    peaks = []
    for day, day_hours in group_by_date(split.hours).items():
        if day not in split.gold:
            continue
        peaks.append(max(float(hour["significant_wave_height"]) for hour in day_hours))
    if not peaks:
        raise RuntimeError("the fitting split contains no Gold Days; nothing can be fitted")
    smallest = min(peaks)
    return (int(smallest / HEIGHT_STEP_M) * HEIGHT_STEP_M, smallest)


def fit_light_wind_exemption(split: Split) -> tuple[float, float, int]:
    """The lowest exemption speed that stops wind blocking any Gold Day in the fitting split.

    ADR 0009's new threshold, and the only condition besides swell period this calibration
    fits. Returns the bar, the calmest-hour wind it had to admit, and how many Gold Days
    needed it at all — the last so the report can say whether the record pinned the number
    down or merely failed to contradict it.

    A day is counted as needing the exemption when **no** hour of it passes on direction and
    speed alone. For such a day the cheapest hour to admit is its calmest, so the exemption
    has to reach that day's minimum wind speed; the bar is the largest of those minima across
    the days that need it. Taking anything higher would admit non-Gold days for nothing,
    which costs precision on exactly the days a Go Call is expensive.
    """
    needed: list[float] = []
    arc = UNFITTED.offshore_wind_arc
    cap = UNFITTED.maximum_wind_speed_kmh
    for day, day_hours in group_by_date(split.hours).items():
        if day not in split.gold:
            continue
        # Through the model's own arc test rather than an inline comparison. `_within` raises
        # on an arc that wraps past north, where the naive comparison this replaced would
        # quietly match no bearing at all — and a fit that silently saw every hour as onshore
        # would set the exemption at the windiest Gold Day and look entirely plausible.
        passes_on_direction = any(
            _within(float(hour["wind_direction"]), arc) and float(hour["wind_speed"]) <= cap
            for hour in day_hours
        )
        if passes_on_direction:
            continue
        needed.append(min(float(hour["wind_speed"]) for hour in day_hours))

    if not needed:
        # Every Gold Day already passes on direction, so nothing in the record says how high
        # the exemption should sit. Report the smallest expressible value rather than a
        # comfortable-looking guess, and let `main` say the record does not constrain it.
        return (LIGHT_WIND_STEP_KMH, 0.0, 0)

    largest = max(needed)
    bar = math.ceil(largest / LIGHT_WIND_STEP_KMH) * LIGHT_WIND_STEP_KMH
    if bar >= cap:
        raise RuntimeError(
            f"the light-wind exemption fits at {bar:g} km/h, at or above the "
            f"{cap:g} km/h cap. Every wind the cap allows would then skip the direction "
            "check and the offshore arc would be dead (thresholds.parse refuses such a "
            "file). A Gold Day needing this much exemption is not a light-wind day, and "
            "ADR 0009's premise does not cover it"
        )
    return (bar, largest, len(needed))


@dataclass(frozen=True)
class SharedCondition:
    """A condition shared by both tiers, and the room it had to spare.

    "Shared" rather than "unfitted" since ADR 0009: height and the two arcs are checked and
    never fitted, but the wind condition now carries a fitted exemption inside it. What all
    of these have in common is that one value serves both tiers, not that nothing was fitted.
    """

    name: str
    observed: str
    threshold: str
    binds: bool


def verify_shared_conditions(split: Split, thresholds: Thresholds) -> list[SharedCondition]:
    """Check that height, swell direction and wind admit every Gold Day in the split.

    None of them is fitted per tier, and this is what makes that defensible rather than
    lazy: if one of them turns out to bind, the claim that period is the only condition
    worth splitting per tier is false and the report says so instead of asserting the
    opposite. This is the check that raised on the full record and produced ADR 0009 —
    wind bound, and the answer was to fit an exemption inside the wind condition rather
    than to quietly widen an arc until the check passed.

    A condition counts as holding for a day if it held in **any** hour of that day, matching
    how a day earns its call — a swell that cleaned up in the evening is not a wind failure.
    """
    directions: list[float] = []
    speeds: list[float] = []
    heights: list[float] = []
    never_held: dict[str, list[str]] = {"swell direction": [], "wind": [], "height": []}

    model = HeuristicBaseline(thresholds)
    for day, day_hours in group_by_date(split.hours).items():
        if day not in split.gold:
            continue
        held: set[str] = set()
        for hour in day_hours:
            readings = {k: v for k, v in hour.items() if k != "at"}
            for outcome in model.predict(readings).conditions:
                if outcome.holds:
                    held.add(outcome.condition.value)
        directions.append(max(float(h["swell_direction"]) for h in day_hours))
        speeds.append(min(float(h["wind_speed"]) for h in day_hours))
        heights.append(max(float(h["significant_wave_height"]) for h in day_hours))
        if "swell direction" not in held:
            never_held["swell direction"].append(day)
        if "wind" not in held:
            never_held["wind"].append(day)
        if "significant wave height" not in held:
            never_held["height"].append(day)

    low, high = thresholds.swell_arc
    wind_low, wind_high = thresholds.offshore_wind_arc
    return [
        SharedCondition(
            name="significant wave height",
            observed=f"{min(heights):.2f}-{max(heights):.2f} m across Gold Days",
            threshold=f">= {thresholds.minimum_significant_wave_height_m:g} m",
            binds=bool(never_held["height"]),
        ),
        SharedCondition(
            name="swell direction",
            observed=f"{min(directions):.0f}-{max(directions):.0f}° across Gold Days",
            threshold=f"{low:g}-{high:g}°",
            binds=bool(never_held["swell direction"]),
        ),
        SharedCondition(
            name="wind",
            observed=f"calmest hour {min(speeds):.0f}-{max(speeds):.0f} km/h across Gold Days",
            # The disjunction ADR 0009 made it, in the order the model evaluates. Printed as
            # a conjunction this table asserted a rule the model stopped applying, in the one
            # place a reader goes to check what the shipped conditions actually are.
            threshold=f"<= {thresholds.light_wind_exemption_kmh:g} km/h, or offshore "
            f"{wind_low:g}-{wind_high:g}° and <= {thresholds.maximum_wind_speed_kmh:g} km/h",
            binds=bool(never_held["wind"]),
        ),
    ]


@dataclass(frozen=True)
class SweepRow:
    period: float
    watch_recall: Score
    go_recall: Score


def sweep(split: Split, height: float, light_wind: float) -> list[SweepRow]:
    """Score every candidate period, as both a Watch bar and a Go Call bar.

    One pass, two readings. A candidate is scored as a Watch bar by pairing it with a Go bar
    high enough to be out of the way, and as a Go bar by pairing it with a Watch bar low
    enough to be out of the way — so each column measures the bar it names and not the
    interaction of the pair.
    """
    rows = []
    floor, ceiling = min(PERIOD_SWEEP), max(PERIOD_SWEEP)
    for period in PERIOD_SWEEP:
        as_watch = candidate(period, max(period + 0.5, ceiling + 0.5), height, light_wind)
        as_go = candidate(min(period - 0.5, floor - 0.5), period, height, light_wind)
        rows.append(
            SweepRow(
                period=period,
                watch_recall=score(split, as_watch, WATCH_OR_BETTER),
                go_recall=score(split, as_go, GO_TIERS),
            )
        )
    return rows


def choose_watch_bar(rows: list[SweepRow]) -> float:
    """The **highest** period bar that still catches every Gold Day in the fitting split.

    Recall-optimised, per ADR 0003: full recall is the constraint, and among the bars that
    achieve it the highest is chosen because it flags fewest days. Taking the lowest bar
    instead would score the same recall while burying it in noise, which is a worse Watch,
    not a safer one.
    """
    full = [row.period for row in rows if row.watch_recall.recall >= 1.0]
    if not full:
        raise RuntimeError(
            "no swell period bar in the sweep catches every Gold Day in the fitting split; "
            "the range of PERIOD_SWEEP is too narrow, or a condition other than period is "
            "blocking one of them"
        )
    return max(full)


def choose_go_bar(rows: list[SweepRow], watch_bar: float) -> float:
    """The **lowest** period bar whose Go Call rate stays inside the stated budget.

    Precision-optimised, per ADR 0003. The budget is the constraint; recall falls as the bar
    rises, so the lowest bar meeting the budget is the one that catches most Gold Days
    without exceeding what a Go Call is allowed to cost the user.

    Constrained to sit strictly above the Watch bar. If nothing in the sweep satisfies both,
    this raises rather than returning a bar that would invert the tiers — `thresholds.parse`
    would refuse the resulting file anyway, and failing here says why.
    """
    within = [
        row.period
        for row in rows
        if row.go_recall.per_season <= GO_CALLS_PER_SEASON_BUDGET and row.period > watch_bar
    ]
    if not within:
        raise RuntimeError(
            f"no swell period bar above the Watch bar of {watch_bar}s keeps Go Calls within "
            f"{GO_CALLS_PER_SEASON_BUDGET:g} per season; the budget and the Watch bar cannot "
            "both be honoured on this record"
        )
    return min(within)


def describe_binding_constraint(rows: list[SweepRow], watch_bar: float, go_bar: float) -> str:
    """Which constraint chose the Go Call bar: the budget, or having to clear the Watch bar.

    `choose_go_bar` takes the lowest bar satisfying both, so whichever constraint the chosen
    bar sits *against* is the one doing the work. If the budget alone would have allowed a
    lower bar, then the budget did not bind and the Go bar is simply one step above the
    Watch bar — which means the record does not pin it down, and anyone reading these
    numbers should know that before treating 13s as a measured quantity.
    """
    within_budget = [
        row.period for row in rows if row.go_recall.per_season <= GO_CALLS_PER_SEASON_BUDGET
    ]
    lowest_affordable = min(within_budget) if within_budget else None
    # The budget is slack exactly when it would already have allowed a bar at or below the
    # Watch bar: everything above that is affordable too, so the only thing left holding the
    # Go bar up is having to clear the Watch bar.
    if lowest_affordable is not None and lowest_affordable <= watch_bar < go_bar:
        return (
            f"the Watch bar rather than the budget — bars from {lowest_affordable:g}s up are "
            f"already within {GO_CALLS_PER_SEASON_BUDGET:g} calls per season, so {go_bar:g}s is "
            "simply the first step above the Watch bar and the record does not distinguish it "
            "from the higher bars that also qualify"
        )
    return f"the budget of {GO_CALLS_PER_SEASON_BUDGET:g} Go Calls per Big-Wave Season"


def translate(thresholds: Thresholds, translations: dict[str, measure.Translation]) -> Thresholds:
    """The fitted bars, restated in the units the live Pipeline Run reads.

    The fit ran on the reanalysis. The deployed system reads Open-Meteo, where the same sea
    reports a shorter swell period — so a bar fitted at 13.5 s here is about 12.9 s there,
    and shipping 13.5 s would silently move the deployed bar half a second stricter than
    anything the Gold Days justify.

    Only the two *wave* quantities are translated. The swell arc is verified rather than
    fitted, and its measured direction offset is 1-3° against an arc 75° wide.

    **The light-wind exemption is deliberately not translated**, and this is not an
    oversight. Height and period are read from the reanalysis during the fit and from
    Open-Meteo in production, which is what makes them need converting. Wind is read from
    ERA5 via `hindcast.wind()` in *both* paths — `operational_hours` and `reanalysis_hours`
    take the same series — so the exemption is already in the units it will be applied in.
    Translating it with a transform fitted on wave height would be arithmetic applied to the
    wrong variable.

    Rounded after translating, not before: a translated bar lands on some number like
    12.8637, and the fitted values are supposed to be numbers a person would choose. Height
    is floored to `HEIGHT_STEP_M`, which can only make the bar more permissive and so cannot
    cost a Gold Day the fit admitted; periods go to one decimal, which is the resolution the
    operational feed reports. Both transforms are increasing, so the Go bar cannot cross
    below the Watch bar and `parse` cannot be handed a set it would refuse.
    """
    height = translations["significant_wave_height_m"]
    period = translations["swell_period_s"]
    return thresholds.replacing(
        minimum_significant_wave_height_m=(
            int(height.apply(thresholds.minimum_significant_wave_height_m) / HEIGHT_STEP_M)
            * HEIGHT_STEP_M
        ),
        watch_minimum_swell_period_s=round(
            period.apply(thresholds.watch_minimum_swell_period_s), 1
        ),
        go_call_minimum_swell_period_s=round(
            period.apply(thresholds.go_call_minimum_swell_period_s), 1
        ),
    )


def _describe_exemption(thresholds: Thresholds, support: tuple[float, int]) -> str:
    """How the light-wind exemption was fitted, and what the record had to say about it.

    ADR 0009 asks that a value the Gold Days do not pin down says so rather than shipping a
    confident-looking number. The count of days that needed the exemption is the whole of
    that evidence: at zero, the bar is an assertion the record neither supports nor
    contradicts, and a reader deciding how much weight to give it needs to know which case
    they are in. It travels in `method` because that is what reaches the API.
    """
    calmest, days_needing = support
    exemption = thresholds.light_wind_exemption_kmh
    if not days_needing:
        return (
            f"The {exemption:g} km/h light-wind exemption (ADR 0009) is the smallest "
            "expressible value, not a measured one: no Gold Day in the fitting split needed "
            "it, so the record does not constrain where it sits."
        )
    return (
        f"The light-wind exemption (ADR 0009) was fitted, not verified: {exemption:g} km/h, "
        f"the lowest value admitting the {days_needing} Gold Days in the fitting split that "
        "no hour passes on direction and speed alone, the calmest hour of the windiest of "
        f"them being {calmest:.1f} km/h."
    )


def write_thresholds(
    thresholds: Thresholds,
    fitted: Thresholds,
    fit: Split,
    test: Split,
    binding: str,
    translations: dict[str, measure.Translation],
    exemption_support: tuple[float, int],
    path: Path,
) -> None:
    """Write the calibrated set where the running system reads it.

    Deliberately the shipped default rather than a file in `output/`. A calibration nobody
    deploys is a report; the point of #12 is that these numbers reach the Decision Model.
    `output/` gets the tables that justify them.

    `thresholds` arrives already translated, and `fitted` carries the reanalysis-unit values
    it was translated from. Both go into `method` rather than into new top-level keys: a
    reader comparing this file against the calibration report would otherwise find two
    different sets of numbers and nothing saying which is which, and `_calibration` in
    `thresholds.py` validates a fixed set of fields and would silently drop anything else.
    """
    body = thresholds.as_dict() | {
        "calibration": {
            "fitted_on": fit.span,
            "validated_on": test.span,
            "gold_days_fitted": len([d for d in fit.gold if d in group_by_date(fit.hours)]),
            "gold_days_validated": len([d for d in test.gold if d in group_by_date(test.hours)]),
            # Leads with what actually chose each bar, not with the criterion that was
            # merely checked. This string reaches the API and can reach a reader, and an
            # earlier version opened on the Go Call budget — true, but not the constraint
            # that selected the number, which the same sentence then had to walk back.
            "method": (
                "Swell period fitted per tier against Gold Days on the Copernicus IBI wave "
                "reanalysis, split on Big-Wave Season boundaries. The Watch bar is the "
                "highest period catching every Gold Day in the fitting split. The Go Call "
                "bar is the lowest period sitting above the Watch bar and within "
                f"{GO_CALLS_PER_SEASON_BUDGET:g} Go Calls per Big-Wave Season; in this fit "
                f"what actually set it was {binding}. Height and both arcs were verified to "
                "block no Gold Day rather than fitted. "
                + _describe_exemption(thresholds, exemption_support)
                + " The wave bars above are in "
                "Open-Meteo units, which is what the Pipeline Run reads; the fit ran in "
                "reanalysis units, where the same sea reports a longer swell period, and "
                "chose "
                f"{fitted.minimum_significant_wave_height_m:g} m / "
                f"{fitted.watch_minimum_swell_period_s:g} s / "
                f"{fitted.go_call_minimum_swell_period_s:g} s. Translated by "
                + "; ".join(t.describe() for t in translations.values())
                + " (analysis/overlap/README.md). The light-wind exemption is not "
                "translated: wind reaches the fit and the Pipeline Run alike from ERA5, so "
                "it is already in the units it is applied in."
            ),
            "source": "analysis/calibration/calibrate.py",
            "fitted_at": date_type.today().isoformat(),
        },
    }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def write_sweep_csv(rows: list[SweepRow]) -> Path:
    path = OUTPUT / "period_sweep.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "minimum_swell_period_s",
                "watch_gold_days_called",
                "watch_gold_days_in_split",
                "watch_days_flagged",
                "watch_flags_per_season",
                "go_gold_days_called",
                "go_days_flagged",
                "go_calls_per_season",
                "go_precision_lower_bound",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    f"{row.period:g}",
                    row.watch_recall.gold_called,
                    row.watch_recall.gold_total,
                    row.watch_recall.flagged,
                    f"{row.watch_recall.per_season:.1f}",
                    row.go_recall.gold_called,
                    row.go_recall.flagged,
                    f"{row.go_recall.per_season:.1f}",
                    f"{row.go_recall.precision_lower_bound:.4f}",
                ]
            )
    return path


def write_report_csv(results: list[tuple[str, str, Score, tuple[int, int]]]) -> Path:
    path = OUTPUT / "calibrated_scores.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "split",
                "tier",
                "gold_days_called",
                "gold_days_in_split",
                "recall",
                "days_flagged",
                "flags_per_season",
                "flagged_that_are_gold",
                "precision_lower_bound",
                # The subset with an instrument behind it, reported beside the whole so a
                # reader can see whether the rule does better on the days that are best
                # attested — and so this figure is in the record rather than only on stdout.
                "buoy_measured_called",
                "buoy_measured_in_split",
            ]
        )
        for split_name, tier, result, (measured_called, measured_total) in results:
            writer.writerow(
                [
                    split_name,
                    tier,
                    result.gold_called,
                    result.gold_total,
                    f"{result.recall:.3f}",
                    result.flagged,
                    f"{result.per_season:.1f}",
                    result.flagged_that_are_gold,
                    f"{result.precision_lower_bound:.4f}",
                    measured_called,
                    measured_total,
                ]
            )
    return path


def split_hours(
    hours: list[dict[str, float | str]], seasons: tuple[str, ...]
) -> list[dict[str, float | str]]:
    """The hours belonging to these Big-Wave Seasons, whole seasons only.

    `season_of` is imported from the backtest rather than reimplemented: it is the same
    October-opening rule CONTEXT.md defines, and two copies of a calendar convention drift.
    """
    return [hour for hour in hours if season_of(str(hour["at"])[:10]) in seasons]


def check() -> int:
    """Self-test the arithmetic, without touching the network or the Hindcast.

    Analysis scripts are lint-only in CI (root README), so the parts that are pure
    arithmetic carry their own check — the same arrangement `gold_days/build.py --check` and
    `backtest/swell.py --check` use. What is worth checking here is the two selection rules,
    because they are the whole calibration and both are easy to write backwards.
    """
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    def row(period: float, watch_recall: float, go_per_season: float) -> SweepRow:
        return SweepRow(
            period=period,
            watch_recall=Score(
                gold_called=int(watch_recall * 10),
                gold_total=10,
                flagged=0,
                flagged_that_are_gold=0,
                seasons=1.0,
            ),
            go_recall=Score(
                gold_called=0,
                gold_total=10,
                flagged=int(go_per_season),
                flagged_that_are_gold=0,
                seasons=1.0,
            ),
        )

    # The Watch bar takes the HIGHEST bar with full recall, not the lowest and not the
    # first. Written backwards it would still produce full recall on the fitting split and
    # look correct in the report, while flagging several times as many days.
    rows = [row(11.0, 1.0, 0), row(12.0, 1.0, 0), row(13.0, 0.8, 0)]
    expect("watch bar picks the highest with full recall", choose_watch_bar(rows), 12.0)

    # The Go bar takes the LOWEST bar inside the budget. Written backwards it would pick the
    # strictest bar in the sweep, scoring near-perfect precision by almost never speaking.
    rows = [row(12.0, 1.0, 20), row(13.0, 1.0, 5), row(14.0, 1.0, 2)]
    expect("go bar picks the lowest inside budget", choose_go_bar(rows, watch_bar=11.0), 13.0)

    # ...and never at or below the Watch bar, whatever the budget says.
    expect("go bar stays above the watch bar", choose_go_bar(rows, watch_bar=13.0), 14.0)

    try:
        choose_go_bar([row(12.0, 1.0, 99)], watch_bar=11.0)
    except RuntimeError:
        pass
    else:
        failures.append("go bar: expected a RuntimeError when no bar meets the budget")

    try:
        choose_watch_bar([row(12.0, 0.5, 0)])
    except RuntimeError:
        pass
    else:
        failures.append("watch bar: expected a RuntimeError when no bar reaches full recall")

    # A candidate that would invert the tiers must be refused by the parser the running
    # system uses, not merely by the chooser above it.
    try:
        candidate(watch_period=13.0, go_period=12.0, height=3.0)
    except ValueError:
        pass
    else:
        failures.append("candidate: expected a refusal for a Go bar below the Watch bar")

    for failure in failures:
        print(f"FAIL {failure}")
    print("calibrate.py --check: " + ("FAILED" if failures else "all checks passed"))
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    OUTPUT.mkdir(parents=True, exist_ok=True)
    gold = load_gold_days()
    hours = reanalysis_hours()

    fit = Split("fitting", FIT_SPAN, split_hours(hours, FIT_SEASONS), gold)
    test = Split("held-out", TEST_SPAN, split_hours(hours, TEST_SEASONS), gold)
    overlap = set(FIT_SEASONS) & set(TEST_SEASONS)
    if overlap:
        raise RuntimeError(
            f"these Big-Wave Seasons appear in both splits: {sorted(overlap)}. The held-out "
            "split would not be held out, and every season counted twice would understate "
            "the Go Call rate the budget is fitted against"
        )
    for split in (fit, test):
        present = [d for d in gold if d in group_by_date(split.hours)]
        print(
            f"{split.name} split {split.span}: {len(group_by_date(split.hours))} days, "
            f"{len(present)} Gold Days, {split.seasons:.0f} seasons"
        )
        if not present:
            raise RuntimeError(f"the {split.name} split contains no Gold Days")

    height, smallest = fit_height(fit)
    print(
        f"\nHeight bar fitted to {height:g} m "
        f"(smallest Gold Day peak in the fitting split: {smallest:.2f} m)"
    )

    # Fitted before the sweep, because the exemption changes which days produce a Go Call and
    # the Go bar is chosen against a Go Calls-per-season budget. Not circular: the exemption
    # is settled entirely by the wind on Gold Days and does not depend on any period bar.
    light_wind, calmest_admitted, days_needing = fit_light_wind_exemption(fit)
    if days_needing:
        print(
            f"\nLight-wind exemption fitted to {light_wind:g} km/h "
            f"(ADR 0009; {days_needing} Gold Days in the fitting split are blocked by the "
            f"offshore arc and need it, the calmest hour of the windiest being "
            f"{calmest_admitted:.1f} km/h)"
        )
    else:
        print(
            f"\nLight-wind exemption set to {light_wind:g} km/h, the smallest expressible "
            "value: no Gold Day in the fitting split needs it, so the record does not "
            "constrain it and this number should not be read as measured"
        )

    print("\nSweeping swell period on the fitting split...")
    rows = sweep(fit, height, light_wind)
    print(
        f"  {'bar':>6s}  {'as Watch: gold':>15s}  {'flags/season':>12s}  "
        f"{'as Go: gold':>12s}  {'calls/season':>12s}"
    )
    for row in rows:
        print(
            f"  {row.period:5.1f}s  "
            f"{f'{row.watch_recall.gold_called}/{row.watch_recall.gold_total}':>15s}  "
            f"{row.watch_recall.per_season:12.1f}  "
            f"{f'{row.go_recall.gold_called}/{row.go_recall.gold_total}':>12s}  "
            f"{row.go_recall.per_season:12.1f}"
        )

    watch_bar = choose_watch_bar(rows)
    go_bar = choose_go_bar(rows, watch_bar)
    print(f"\nWatch bar:    {watch_bar:g}s  (highest with full recall on the fitting split)")
    print(f"Go Call bar:  {go_bar:g}s  (lowest within {GO_CALLS_PER_SEASON_BUDGET:g} calls/season)")

    # Which of the two constraints actually chose the Go bar. Worth printing because the
    # answer here is not the flattering one: the budget is slack, and reporting the Go bar
    # as "the precision target's doing" when the target never bit would be a claim the
    # record does not support.
    binding = describe_binding_constraint(rows, watch_bar, go_bar)
    print(f"  binding constraint: {binding}")

    chosen = candidate(watch_bar, go_bar, height, light_wind)

    print("\nConditions shared by both tiers, checked to admit every Gold Day:")
    binding_conditions = []
    for shared in verify_shared_conditions(fit, chosen):
        mark = "BINDS" if shared.binds else "clear"
        print(f"  {shared.name:26s} {shared.observed:44s} {shared.threshold:34s} {mark}")
        if shared.binds:
            binding_conditions.append(shared.name)
    if binding_conditions:
        raise RuntimeError(
            f"these conditions block a Gold Day in the fitting split: {binding_conditions}. The "
            "calibration assumes only swell period binds, and that assumption is now false; "
            "they must be fitted rather than verified before these thresholds are shipped.\n\n"
            "This fired the first time #39 ran the fit on 25 Gold Days instead of 6, and it "
            "is not a threshold problem. Six fitting Gold Days are blocked by **wind**, and "
            "every one of them is blocked by the arc rather than the speed: 2013-10-28, "
            "2015-10-27, 2017-02-28, 2018-02-11, 2019-11-13 and 2020-02-17 had calmest-hour "
            "winds of 4-16 km/h, far under the 35 km/h cap, from bearings of 225-346 degrees "
            "which fall outside the offshore arc. `HeuristicBaseline.predict` requires the "
            "arc AND the speed, so a dead-calm 4 km/h breeze from the wrong quarter fails the "
            "condition as surely as a gale. On the 6 recent Gold Days #12 fitted, that never "
            "showed.\n\n"
            "Fixing it means changing the shipped Heuristic Baseline, which ADR 0006 keeps "
            "fixed as the permanent benchmark — filed as **#40**, which exempts light winds "
            "from the direction arc and which #39 is blocked by. Raising here is deliberate: "
            "it stops #39 shipping thresholds fitted under an assumption its own data "
            "disproves."
        )

    results = []
    for split in (fit, test):
        for label, tiers in (("watch_or_better", WATCH_OR_BETTER), ("go_call", GO_TIERS)):
            results.append(
                (
                    split.name,
                    label,
                    score(split, chosen, tiers),
                    buoy_measured_recall(split, chosen, tiers),
                )
            )

    print(
        f"\n{'split':10s} {'tier':16s} {'recall':>10s} {'flagged':>8s} "
        f"{'per season':>11s} {'precision >=':>13s}"
    )
    for split_name, tier, result, _measured in results:
        print(
            f"{split_name:10s} {tier:16s} "
            f"{f'{result.gold_called}/{result.gold_total}':>10s} "
            f"{result.flagged:>8d} {result.per_season:>11.1f} "
            f"{result.precision_lower_bound:>13.0%}"
        )

    print("\nRecall on the buoy-measured subset, where an instrument recorded the size:")
    for split in (fit, test):
        for label, tiers in (("watch_or_better", WATCH_OR_BETTER), ("go_call", GO_TIERS)):
            called, total = buoy_measured_recall(split, chosen, tiers)
            reading = f"{called}/{total}" if total else "none in this split"
            print(f"  {split.name:10s} {label:16s} {reading}")

    # Translated only now, after everything above has been scored. Every number printed and
    # every table written describes the reanalysis the fit ran on; only the shipped file is
    # restated in the units the Pipeline Run reads.
    translations = measure.fit_translations()
    shipped = translate(chosen, translations)
    print("\nTranslating the fitted bars into the units the Pipeline Run reads:")
    for translation in translations.values():
        print(f"  {translation.describe()}")
    print(
        f"  height    {chosen.minimum_significant_wave_height_m:g} m  -> "
        f"{shipped.minimum_significant_wave_height_m:g} m\n"
        f"  Watch bar {chosen.watch_minimum_swell_period_s:g} s  -> "
        f"{shipped.watch_minimum_swell_period_s:g} s\n"
        f"  Go bar    {chosen.go_call_minimum_swell_period_s:g} s  -> "
        f"{shipped.go_call_minimum_swell_period_s:g} s"
    )

    sweep_path = write_sweep_csv(rows)
    report_path = write_report_csv(results)
    write_thresholds(
        shipped,
        chosen,
        fit,
        test,
        binding,
        translations,
        (calmest_admitted, days_needing),
        DEFAULT_PATH,
    )
    print(f"\nWrote {sweep_path.relative_to(ROOT)}")
    print(f"Wrote {report_path.relative_to(ROOT)}")
    print(f"Wrote {DEFAULT_PATH.relative_to(ROOT)}  <- the file the running system reads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
