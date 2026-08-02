"""Fitting the Decision Model's thresholds to the Gold Days, and validating them held out.

Ticket #12. #11 established the benchmark and found what was wrong with it; this chooses
the numbers, writes them where the running system reads them, and reports what they score
on years the fit never saw.

**The real rule, not a copy.** `HeuristicBaseline` and `decide` are imported from the
running system and driven with candidate thresholds. A reimplementation here would drift
from the thing it calibrates, and the drift would ship.

**Only swell period is fitted per tier.** #11 measured that period blocked all six missed
Gold Days and that height, direction and wind blocked none — so period is the only
condition the evidence can distinguish, and the only place ADR 0003's recall tier and
precision tier can genuinely differ. Fitting arcs to six Gold Days would narrow them onto
noise while changing no call. `verify_shared_conditions` checks they admit every Gold Day
and reports the margin instead, which is the honest version of the same claim.

**Chronological split, matching #11.** Fitted on 2022-2023, validated on 2024-2025 — the
same split the swell reconstruction used, and the same direction the system runs in: fit on
the past, apply to the future. The held-out set holds three Gold Days. That is far too few
to be reassuring, it is stated wherever these numbers are reported, and the interface says
it too.

Run:
    .venv/Scripts/python.exe analysis/calibration/calibrate.py
    .venv/Scripts/python.exe analysis/calibration/calibrate.py --check
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import date as date_type
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

sys.path.insert(0, str(ROOT / "analysis" / "backtest"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

import backtest  # noqa: E402
from backtest import GoldDay, load_gold_days, operational_hours, season_of  # noqa: E402
from nazarenow.days import group_by_date  # noqa: E402
from nazarenow.decision import Status, decide, strength  # noqa: E402
from nazarenow.models.heuristic import HeuristicBaseline  # noqa: E402
from nazarenow.thresholds import DEFAULT_PATH, Thresholds, parse  # noqa: E402

LEAD_TIME_DAYS = backtest.LEAD_TIME_DAYS
GO_TIERS = backtest.GO_TIERS
WATCH_OR_BETTER = backtest.WATCH_OR_BETTER

FIT_SEASONS = ("2021/22", "2022/23")
TEST_SEASONS = ("2023/24", "2024/25", "2025/26")
FIT_SPAN = "2021/22-2022/23"
TEST_SPAN = "2023/24-2025/26"

"""Split on Big-Wave Season boundaries, not calendar years.

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
        # Placeholders. Every candidate replaces all three; `parse` will not accept a set
        # without them, and a set that could omit one would silently inherit whatever these
        # said.
        "minimum_significant_wave_height_m": 3.0,
        "watch_minimum_swell_period_s": 12.0,
        "go_call_minimum_swell_period_s": 13.0,
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


def candidate(watch_period: float, go_period: float, height: float) -> Thresholds:
    """A threshold set to try, built through the same parser the running system uses.

    Going through `parse` rather than constructing `Thresholds` directly means a candidate
    the deployed system would refuse to load can never be scored here and recommended.
    """
    return UNFITTED.replacing(
        minimum_significant_wave_height_m=height,
        watch_minimum_swell_period_s=watch_period,
        go_call_minimum_swell_period_s=go_period,
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


@dataclass(frozen=True)
class SharedCondition:
    """A condition that was checked rather than fitted, and the room it had to spare."""

    name: str
    observed: str
    threshold: str
    binds: bool


def verify_shared_conditions(split: Split, thresholds: Thresholds) -> list[SharedCondition]:
    """Check that height, swell direction and wind admit every Gold Day in the split.

    These are not fitted, and this is what makes that defensible rather than lazy: if one
    of them turns out to bind, the claim that period is the only condition worth splitting
    per tier is false and the report says so instead of asserting the opposite.

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
            threshold=f"offshore {wind_low:g}-{wind_high:g}°, <= "
            f"{thresholds.maximum_wind_speed_kmh:g} km/h",
            binds=bool(never_held["wind"]),
        ),
    ]


@dataclass(frozen=True)
class SweepRow:
    period: float
    watch_recall: Score
    go_recall: Score


def sweep(split: Split, height: float) -> list[SweepRow]:
    """Score every candidate period, as both a Watch bar and a Go Call bar.

    One pass, two readings. A candidate is scored as a Watch bar by pairing it with a Go bar
    high enough to be out of the way, and as a Go bar by pairing it with a Watch bar low
    enough to be out of the way — so each column measures the bar it names and not the
    interaction of the pair.
    """
    rows = []
    floor, ceiling = min(PERIOD_SWEEP), max(PERIOD_SWEEP)
    for period in PERIOD_SWEEP:
        as_watch = candidate(period, max(period + 0.5, ceiling + 0.5), height)
        as_go = candidate(min(period - 0.5, floor - 0.5), period, height)
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


def write_thresholds(
    thresholds: Thresholds, fit: Split, test: Split, binding: str, path: Path
) -> None:
    """Write the calibrated set where the running system reads it.

    Deliberately the shipped default rather than a file in `output/`. A calibration nobody
    deploys is a report; the point of #12 is that these numbers reach the Decision Model.
    `output/` gets the tables that justify them.
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
                "Swell period fitted per tier against Gold Days on the real Swell "
                "partition, split on Big-Wave Season boundaries. The Watch bar is the "
                "highest period catching every Gold Day in the fitting split. The Go Call "
                "bar is the lowest period sitting above the Watch bar and within "
                f"{GO_CALLS_PER_SEASON_BUDGET:g} Go Calls per Big-Wave Season; in this fit "
                f"what actually set it was {binding}. Height, swell arc and wind were "
                "verified to block no Gold Day rather than fitted."
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
    hours = operational_hours()

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

    print("\nSweeping swell period on the fitting split...")
    rows = sweep(fit, height)
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

    chosen = candidate(watch_bar, go_bar, height)

    print("\nConditions verified rather than fitted:")
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
            "they must be fitted rather than verified before these thresholds are shipped"
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

    sweep_path = write_sweep_csv(rows)
    report_path = write_report_csv(results)
    write_thresholds(chosen, fit, test, binding, DEFAULT_PATH)
    print(f"\nWrote {sweep_path.relative_to(ROOT)}")
    print(f"Wrote {report_path.relative_to(ROOT)}")
    print(f"Wrote {DEFAULT_PATH.relative_to(ROOT)}  <- the file the running system reads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
