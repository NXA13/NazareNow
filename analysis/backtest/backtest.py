"""Scoring the Heuristic Baseline against the Hindcast, and writing the benchmark report.

Ticket #11. Per ADR 0006 the rule of thumb is the number every later model must beat, and
no accuracy figure in this project is reported without it.

**The real baseline, not a copy of it.** `HeuristicBaseline` and `decide` are imported from
the running system. A reimplementation here would drift from the thing it claims to
benchmark, and the drift would show up as the learned model in #13 beating a rule nobody
actually ships.

**What this measures, and what it does not.** A Hindcast is what the ocean did, not what a
forecast said it would do. So this scores the *rule* given perfect knowledge of Offshore
Conditions — its ceiling. Real Go Calls are issued days ahead from a forecast that is
wrong by an amount ticket #14 measures, and will do worse. Reading these numbers as the
system's accuracy would overstate it.

**One headline panel, since #39.** This file used to report two and refuse to average them:
an operational panel that read the real Swell partition but only reached back to 2022, and a
reconstructed panel that reached 2011 by estimating Swell from Combined Sea badly enough that
`swell.py` called it too weak to carry a verdict. There was no single number for the record
because no single source spanned it.

The Copernicus reanalysis spans it. The headline is now one panel over 2011-2026 reading a
real Swell partition throughout, scoring all 38 Gold Days instead of 9.

The other two panels are kept **as diagnostics, not as results**. The operational panel is
the tie to production — the exact variables the live Pipeline Run reads, on the overlap where
they exist — and the reconstructed panel is what the reanalysis replaced, kept so the size of
the improvement is visible rather than asserted. Neither is the answer to "how good is the
baseline"; the reanalysis panel is.

Run:
    .venv/Scripts/python.exe analysis/backtest/backtest.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import hindcast
import reanalysis
import swell
from swell import BearingOffset, QuantileMap

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analysis" / "overlap"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))

import measure  # noqa: E402
from nazarenow.days import group_by_date  # noqa: E402
from nazarenow.decision import Status, decide, strength  # noqa: E402
from nazarenow.models.heuristic import HeuristicBaseline  # noqa: E402
from nazarenow.thresholds import Thresholds  # noqa: E402
from nazarenow.thresholds import load as load_thresholds

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
GOLD = HERE.parent / "gold_days" / "gold_days.jsonl"

LEAD_TIME_DAYS = 3
"""The Lead Time every hour is scored at.

Chosen because it sits inside both bands at once — past `CONFIRMED_THROUGH` so a Watch is
reachable, within `GO_CALL_THROUGH` so a Go Call is too — which lets a single pass produce
both tiers from the same conditions. Nothing else in the score depends on it: the Hindcast
carries no Lead Time of its own, and the Heuristic Baseline's conditions do not vary with
one. Only the tier names do.
"""

# The Big-Wave Season runs October through March and is named for the year it opens in
# (CONTEXT.md). A season is the unit a reader thinks in, and splitting one across two
# calendar years destroys it.
SEASON_OPENS = 10


def season_of(date: str) -> str:
    year, month = int(date[:4]), int(date[5:7])
    opening = year if month >= SEASON_OPENS else year - 1
    return f"{opening}/{str(opening + 1)[2:]}"


def in_big_wave_season(date: str) -> bool:
    return int(date[5:7]) >= SEASON_OPENS or int(date[5:7]) <= 3


@dataclass(frozen=True)
class GoldDay:
    date: str
    tier: str
    evidence_class: str


def load_gold_days() -> dict[str, GoldDay]:
    days = {}
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        days[entry["date"]] = GoldDay(
            date=entry["date"],
            tier=entry["tier"],
            evidence_class=entry["evidence_class"],
        )
    return days


@dataclass(frozen=True)
class DayCall:
    """The strongest call the baseline would have supported on one Nazaré local day."""

    date: str
    status: Status
    hours_scored: int
    peak_significant_wave_height: float


def call_days(
    hours: list[dict[str, float | str]], thresholds: Thresholds | None = None
) -> dict[str, DayCall]:
    """Score every hour, then take each day's strongest call.

    A day is called at the best call any of its hours supports, matching how the Pipeline
    Run reduces a day — `decision.strength` exists for exactly this and is imported rather
    than reimplemented.

    Defaults to the shipped calibration, so the headline panels score what the system
    actually issues. `period_sensitivity` passes its own set instead.
    """
    model = HeuristicBaseline(thresholds)
    calls: dict[str, DayCall] = {}
    for date, day_hours in group_by_date(hours).items():
        best = Status.NONE
        peak = 0.0
        for hour in day_hours:
            readings = {k: v for k, v in hour.items() if k != "at"}
            prediction = model.predict(readings)
            call = decide(prediction, LEAD_TIME_DAYS)
            if strength(call.status) > strength(best):
                best = call.status
            peak = max(peak, float(readings["significant_wave_height"]))
        calls[date] = DayCall(
            date=date,
            status=best,
            hours_scored=len(day_hours),
            peak_significant_wave_height=peak,
        )
    return calls


def operational_hours() -> list[dict[str, float | str]]:
    """2022-2025, with the real Swell partition. No substitution anywhere."""
    sea = hindcast.operational_swell()
    air = hindcast.wind()
    hours = []
    for at, reading in sorted(sea.readings.items()):
        weather = air.readings.get(at)
        if weather is None:
            continue
        hours.append(
            {
                "at": at,
                "significant_wave_height": reading["wave_height"],
                "swell_period": reading["swell_wave_period"],
                "swell_direction": reading["swell_wave_direction"],
                "wind_speed": weather["wind_speed_10m"],
                "wind_direction": weather["wind_direction_10m"],
            }
        )
    return hours


def reanalysis_hours(
    product: reanalysis.Product = reanalysis.IBI,
) -> list[dict[str, float | str]]:
    """2011-2026, with the real Swell partition. No reconstruction anywhere.

    This is what #39 buys: the same row shape `operational_hours` produces, spanning the
    whole record instead of its last four years, read from a model rather than rebuilt from
    a Combined Sea by regression. It is what lets the calibration see 38 Gold Days instead
    of 9, and what collapses this file's two-panel split.

    **Swell is the combined field, not the primary train.** `analysis/overlap/README.md`
    measured that Open-Meteo's `swell_wave_*` — the variables the shipped thresholds were
    fitted on — track the two trains combined rather than `*_SW1` alone, and that taking
    SW1 alone under-reads by up to a metre exactly on the big two-train seas that make Gold
    Days. So the height is the root sum of squares and the period and direction are
    energy-weighted, which is the mapping that measurement selected.

    **These numbers are in reanalysis units and are not interchangeable with Open-Meteo's.**
    The same sea reads about half a second longer here. That is fine inside a fit, which is
    self-consistent, and fatal if a bar fitted here were shipped untranslated — see
    `calibrate.py`, which does the translating.

    The wind still comes from ERA5 via `hindcast.wind()`: neither reanalysis carries a wind
    variable, and the Heuristic Baseline needs one. That is unchanged from the operational
    panel and is not a substitution this ticket introduces.
    """
    sea = reanalysis.read(product)
    air = hindcast.wind()
    hours = []
    for reading in sea.rows():
        at = str(reading["at"])
        weather = air.readings.get(at)
        if weather is None:
            continue
        sw1_height = float(reading["VHM0_SW1"])
        sw2_height = float(reading["VHM0_SW2"])
        hours.append(
            {
                "at": at,
                "significant_wave_height": float(reading["VHM0"]),
                "swell_period": measure.energy_weighted(
                    float(reading["VTM01_SW1"]),
                    sw1_height,
                    float(reading["VTM01_SW2"]),
                    sw2_height,
                ),
                "swell_direction": measure.vector_mean_direction(
                    float(reading["VMDR_SW1"]),
                    sw1_height,
                    float(reading["VMDR_SW2"]),
                    sw2_height,
                ),
                "wind_speed": weather["wind_speed_10m"],
                "wind_direction": weather["wind_direction_10m"],
            }
        )
    return hours


@dataclass(frozen=True)
class Reconstruction:
    """The fitted Combined Sea to Swell bridge, and its held-out report card.

    `period` maps ERA5's **peak** period. Peak period is the better predictor of Swell
    period — judged on the same hours, it halves the error of mean period and recovers
    more of the threshold crossings — and the span it is used on, 2011-2021, has it for
    every hour. It is unavailable only from 2024-11, inside the operational panel, which
    reconstructs nothing.
    """

    period: QuantileMap
    direction: BearingOffset
    period_agreement: swell.Agreement
    mean_period_agreement: swell.Agreement
    direction_within_15: float
    fitted_on_hours: int
    tested_on_hours: int


def fit_reconstruction() -> Reconstruction:
    """Fit on 2022-2023 and validate on 2024-2025.

    Both halves come from the overlap where ERA5 and the operational model describe the
    same hours, so the fit never sees the years it is later applied to (2011-2021), and
    the validation never sees the years it was fitted on.

    The two period candidates are judged on **identical hours** — those where ERA5 still
    carries peak period — because scoring them on different windows would compare the
    predictors and the windows at once and credit the difference to whichever was being
    argued for.
    """
    # The shipped Go Call bar, read from the calibration rather than restated here. The
    # reconstruction's report card is about whether it can carry a threshold decision, so
    # the threshold it is scored at has to be the one the system actually uses (#12).
    minimum_swell_period_s = load_thresholds().go_call_minimum_swell_period_s

    sea = hindcast.combined_sea()
    ops = hindcast.operational_swell()
    shared = sorted(set(sea.readings) & set(ops.readings))
    with_peak = [at for at in shared if hindcast.PEAK_PERIOD in sea.readings[at]]

    fit = [at for at in with_peak if at[:4] in swell.FIT_YEARS]
    test = [at for at in with_peak if at[:4] in swell.TEST_YEARS]
    if not fit or not test:
        raise RuntimeError(
            "the overlap has no hours carrying peak period in both the fitting and test "
            "years; the reconstruction cannot be validated"
        )

    target = [ops.readings[at]["swell_wave_period"] for at in fit]
    actual = [ops.readings[at]["swell_wave_period"] for at in test]

    period = QuantileMap.fit([sea.readings[at][hindcast.PEAK_PERIOD] for at in fit], target)
    period_agreement = swell.agreement(
        [period.apply(sea.readings[at][hindcast.PEAK_PERIOD]) for at in test],
        actual,
        threshold=minimum_swell_period_s,
    )

    # The alternative, kept so the report shows the comparison rather than asserting it.
    mean_map = QuantileMap.fit([sea.readings[at]["wave_period"] for at in fit], target)
    mean_agreement = swell.agreement(
        [mean_map.apply(sea.readings[at]["wave_period"]) for at in test],
        actual,
        threshold=minimum_swell_period_s,
    )

    direction = BearingOffset.fit(
        [sea.readings[at]["wave_direction"] for at in fit],
        [ops.readings[at]["swell_wave_direction"] for at in fit],
    )
    within = swell.bearing_agreement(
        [direction.apply(sea.readings[at]["wave_direction"]) for at in test],
        [ops.readings[at]["swell_wave_direction"] for at in test],
        within=15.0,
    )

    return Reconstruction(
        period=period,
        direction=direction,
        period_agreement=period_agreement,
        mean_period_agreement=mean_agreement,
        direction_within_15=within,
        fitted_on_hours=len(fit),
        tested_on_hours=len(test),
    )


def reconstructed_hours(
    reconstruction: Reconstruction, before: str, gold: dict[str, GoldDay]
) -> list[dict[str, float | str]]:
    """2011 up to `before`, with Swell estimated from Combined Sea.

    Raises rather than quietly scoring a short record if any Gold Day in the span loses
    hours. Requiring peak period costs nothing here — ERA5 carries it for every hour
    before 2024-11 — but "costs nothing" is a claim about the data, and this project has
    been bitten twice by data that looked complete and was not, so it is checked instead
    of believed.
    """
    sea = hindcast.combined_sea()
    air = hindcast.wind()
    hours = []
    dropped: Counter[str] = Counter()
    for at, reading in sorted(sea.readings.items()):
        if at >= before:
            continue
        weather = air.readings.get(at)
        if weather is None or hindcast.PEAK_PERIOD not in reading:
            dropped[at[:10]] += 1
            continue
        hours.append(
            {
                "at": at,
                # Not reconstructed: the live pipeline's `significant_wave_height` is
                # Open-Meteo's `wave_height`, and ERA5's `wave_height` is the same
                # quantity from a different model. Mapping it onto itself would add error
                # and call it correction.
                "significant_wave_height": reading["wave_height"],
                "swell_period": reconstruction.period.apply(reading[hindcast.PEAK_PERIOD]),
                "swell_direction": reconstruction.direction.apply(reading["wave_direction"]),
                "wind_speed": weather["wind_speed_10m"],
                "wind_direction": weather["wind_direction_10m"],
            }
        )

    lost_gold = {date: count for date, count in dropped.items() if date in gold}
    if lost_gold:
        raise RuntimeError(
            f"the reconstruction would score these Gold Days on an incomplete record: {lost_gold}"
        )
    return hours


@dataclass(frozen=True)
class Panel:
    """One scored span of the record."""

    name: str
    span: str
    calls: dict[str, DayCall]
    gold: dict[str, GoldDay]

    @property
    def gold_in_span(self) -> list[GoldDay]:
        return [g for date, g in sorted(self.gold.items()) if date in self.calls]

    def tier_recall(self, *statuses: Status) -> tuple[int, int]:
        """How many Gold Days in this span earned at least one of these calls."""
        gold = self.gold_in_span
        hit = sum(1 for g in gold if self.calls[g.date].status in statuses)
        return hit, len(gold)

    def flagged(self, *statuses: Status) -> list[str]:
        return sorted(d for d, c in self.calls.items() if c.status in statuses)

    def precision_lower_bound(self, *statuses: Status) -> tuple[int, int]:
        """Flagged days that are known Gold Days, over all flagged days.

        A **lower bound**, and the report must call it one. A Gold Day is a day somebody
        documented — a contest ran, a record was ratified. A day this rule flags that is
        not on the list is not thereby a false positive; it may be an XXL Day nobody
        photographed. Reporting this as precision would understate the rule and would
        reward a later model for fitting who happened to be holding a camera.
        """
        flagged = self.flagged(*statuses)
        return sum(1 for d in flagged if d in self.gold), len(flagged)


GO_TIERS = (Status.GO, Status.CONFIRMED)
WATCH_OR_BETTER = (Status.WATCH, Status.GO, Status.CONFIRMED)


def condition_shortfall(hours: list[dict[str, float | str]], dates: list[str]) -> Counter[str]:
    """Which conditions never held, on days that mattered.

    The headline recall says how often the rule missed a Gold Day. This says why, which is
    the part ticket #12 can act on: a threshold that blocks nine Gold Days out of ten is a
    different problem from four thresholds each blocking a few.

    A condition counts as failed for a day only if it held in **no** hour of that day, so a
    swell that arrived in the evening is not recorded as a direction failure.
    """
    model = HeuristicBaseline()
    wanted = set(dates)
    held: dict[str, set[str]] = {date: set() for date in dates}
    for date, day_hours in group_by_date(hours).items():
        if date not in wanted:
            continue
        for hour in day_hours:
            prediction = model.predict({k: v for k, v in hour.items() if k != "at"})
            for outcome in prediction.conditions:
                if outcome.holds:
                    held[date].add(outcome.condition.value)

    every = {o.condition.value for o in model.predict(_CALM).conditions}
    shortfall: Counter[str] = Counter()
    for date in dates:
        for condition in every - held[date]:
            shortfall[condition] += 1
    return shortfall


PERIOD_SWEEP = (10.0, 11.0, 12.0, 13.0, 14.0, 15.0)


def period_sensitivity(
    hours: list[dict[str, float | str]], gold: dict[str, GoldDay]
) -> list[tuple[float, int, int, int]]:
    """Gold Days called and Go Calls issued, as the Go Call swell period bar varies.

    **Diagnostic, not the calibration.** This is the question the backtest raised — period
    blocks every missed Gold Day, so how much of the miss is the threshold's doing? — scored
    across the whole operational panel. `analysis/calibration/` is what actually chooses the
    values, and it does so on the fitting split alone with a held-out split kept back. The
    two disagree by construction: a sweep that has seen every Gold Day cannot also validate
    against them.

    Each row varies the Go bar and puts the Watch bar half a second below it, so the row
    measures the bar it names rather than the interaction of the pair. The threshold set is
    built through the running system's own parser and handed to the real model, for the same
    reason the rest of this file imports the baseline instead of copying it — and, unlike the
    module-constant reassignment this replaced, it leaves no global state for a concurrent
    reader to observe mid-sweep.
    """
    shipped = load_thresholds()
    rows = []
    for threshold in PERIOD_SWEEP:
        calls = call_days(hours, _at_go_bar(shipped, threshold))
        in_span = [d for d in gold if d in calls]
        called = sum(1 for d in in_span if calls[d].status in GO_TIERS)
        issued = sum(1 for c in calls.values() if c.status in GO_TIERS)
        rows.append((threshold, called, len(in_span), issued))
    return rows


def _at_go_bar(shipped: Thresholds, go_bar: float) -> Thresholds:
    """The shipped calibration with its Go Call period bar moved, everything else held.

    The Watch bar moves with it, half a second below, so each row measures the Go bar it
    names rather than the interaction of the pair. The calibration is dropped because a
    swept set is not the fit — carrying the provenance forward would let a diagnostic row
    describe itself as the calibrated rule.
    """
    return shipped.replacing(
        watch_minimum_swell_period_s=go_bar - 0.5,
        go_call_minimum_swell_period_s=go_bar,
        calibration=None,
    )


_CALM: dict[str, float] = {
    "significant_wave_height": 0.0,
    "swell_period": 0.0,
    "swell_direction": 0.0,
    "wind_speed": 0.0,
    "wind_direction": 90.0,
}
"""Any readings will do — this exists only to ask the model which conditions it judges,
rather than hard-coding a list here that could drift from the model's own."""


def write_daily_csv(panels: list[Panel]) -> Path:
    path = OUTPUT / "daily_calls.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "panel",
                "date",
                "season",
                "big_wave_season",
                "call",
                "hours_scored",
                "peak_significant_wave_height_m",
                "gold_day",
                "gold_tier",
                "evidence_class",
            ]
        )
        for panel in panels:
            for date in sorted(panel.calls):
                call = panel.calls[date]
                gold = panel.gold.get(date)
                writer.writerow(
                    [
                        panel.name,
                        date,
                        season_of(date),
                        "yes" if in_big_wave_season(date) else "no",
                        call.status.value,
                        call.hours_scored,
                        f"{call.peak_significant_wave_height:.2f}",
                        "yes" if gold else "no",
                        gold.tier if gold else "",
                        gold.evidence_class if gold else "",
                    ]
                )
    return path


def write_sensitivity_csv(rows: list[tuple[float, int, int, int]]) -> Path:
    path = OUTPUT / "period_sensitivity.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["minimum_swell_period_s", "gold_days_called", "gold_days_in_span", "go_calls_issued"]
        )
        writer.writerows(rows)
    return path


def write_summary_csv(panels: list[Panel]) -> Path:
    path = OUTPUT / "summary.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "panel",
                "span",
                "days_scored",
                "gold_days_in_span",
                "tier",
                "gold_days_called",
                "recall",
                "days_flagged",
                "flagged_that_are_gold",
                "precision_lower_bound",
            ]
        )
        for panel in panels:
            for label, statuses in (
                ("watch_or_better", WATCH_OR_BETTER),
                ("go_call", GO_TIERS),
            ):
                hit, total = panel.tier_recall(*statuses)
                known, flagged = panel.precision_lower_bound(*statuses)
                writer.writerow(
                    [
                        panel.name,
                        panel.span,
                        len(panel.calls),
                        total,
                        label,
                        hit,
                        f"{hit / total:.3f}" if total else "",
                        flagged,
                        known,
                        f"{known / flagged:.4f}" if flagged else "",
                    ]
                )
    return path


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    gold = load_gold_days()

    print("Fitting the Combined Sea to Swell reconstruction...")
    reconstruction = fit_reconstruction()
    print(
        f"  fitted on {reconstruction.fitted_on_hours} hours of the 2022-2023 overlap, "
        f"tested on {reconstruction.tested_on_hours}"
    )
    print("  " + reconstruction.period_agreement.line("swell period from PEAK period"))
    print("  " + reconstruction.mean_period_agreement.line("swell period from mean period"))
    print(f"  swell direction within 15 degrees: {reconstruction.direction_within_15:.0%}")
    print(f"  bearing offset applied: {reconstruction.direction.degrees:+.1f} degrees")

    print("\nScoring...")
    rea_hours = reanalysis_hours()
    op_hours = operational_hours()
    rec_hours = reconstructed_hours(reconstruction, hindcast.OPERATIONAL_START, gold)

    # The headline. One panel, the whole record, a real Swell partition throughout — which is
    # what #39 bought and what the two-panel split existed for want of.
    #
    # Scored against the shipped bars restated in reanalysis units. The shipped file is
    # written in Open-Meteo units, and the same sea reads about half a second longer in the
    # reanalysis: applying those bars unconverted would fire on 1311 hours where the live
    # feed fires on 576 (`analysis/overlap/README.md`), and the extra Go Calls would look
    # like a finding instead of a unit mismatch.
    translations = measure.fit_translations()
    period = translations["swell_period_s"]
    height = translations["significant_wave_height_m"]
    shipped = load_thresholds()
    in_reanalysis_units = shipped.replacing(
        minimum_significant_wave_height_m=height.invert(shipped.minimum_significant_wave_height_m),
        watch_minimum_swell_period_s=period.invert(shipped.watch_minimum_swell_period_s),
        go_call_minimum_swell_period_s=period.invert(shipped.go_call_minimum_swell_period_s),
    )
    print(
        f"  shipped bars {shipped.minimum_significant_wave_height_m:g} m / "
        f"{shipped.watch_minimum_swell_period_s:g} s / "
        f"{shipped.go_call_minimum_swell_period_s:g} s restated in reanalysis units as "
        f"{in_reanalysis_units.minimum_significant_wave_height_m:.2f} m / "
        f"{in_reanalysis_units.watch_minimum_swell_period_s:.2f} s / "
        f"{in_reanalysis_units.go_call_minimum_swell_period_s:.2f} s"
    )
    reanalysis_panel = Panel(
        name="reanalysis",
        span=f"{rea_hours[0]['at'][:4]}-{rea_hours[-1]['at'][:4]}",
        calls=call_days(rea_hours, in_reanalysis_units),
        gold=gold,
    )
    # Diagnostics. `operational` is the tie to production, on the overlap where the live
    # variables exist; `reconstructed` is what the reanalysis replaced, kept so the size of
    # the improvement can be read rather than asserted. Neither answers "how good is the
    # baseline" — the panel above does.
    operational = Panel(
        name="operational (diagnostic)",
        span=f"{hindcast.OPERATIONAL_START[:4]}-{hindcast.END[:4]}",
        calls=call_days(op_hours),
        gold=gold,
    )
    reconstructed = Panel(
        name="reconstructed (superseded)",
        span=f"{hindcast.START[:4]}-2021",
        calls=call_days(rec_hours),
        gold=gold,
    )
    panels = [reanalysis_panel, operational, reconstructed]

    for panel in panels:
        counts = Counter(c.status.value for c in panel.calls.values())
        hit, total = panel.tier_recall(*WATCH_OR_BETTER)
        go_hit, _ = panel.tier_recall(*GO_TIERS)
        known, flagged = panel.precision_lower_bound(*GO_TIERS)
        print(f"\n  {panel.name} ({panel.span}): {len(panel.calls)} days, {total} Gold Days")
        print(f"    calls: {dict(counts)}")
        print(f"    Watch or better on Gold Days: {hit}/{total}")
        print(f"    Go Call on Gold Days:         {go_hit}/{total}")
        print(f"    Go Calls issued: {flagged}, of which known Gold Days: {known}")

    for panel, hours in (
        (reanalysis_panel, rea_hours),
        (operational, op_hours),
        (reconstructed, rec_hours),
    ):
        missed = [g.date for g in panel.gold_in_span if panel.calls[g.date].status is Status.NONE]
        if not missed:
            continue
        shortfall = condition_shortfall(hours, missed)
        print(f"\n  why {panel.name} missed {len(missed)} Gold Days entirely:")
        for condition, count in shortfall.most_common():
            print(f"    {condition:26s} never held on {count} of them")

    print("\n  swell period sensitivity, operational panel (diagnostic for #12):")
    print(f"    {'threshold':>9s}  {'Gold Days called':>16s}  {'Go Calls issued':>15s}")
    sweep = period_sensitivity(op_hours, gold)
    for threshold, called, total, issued in sweep:
        print(f"    {threshold:8.0f}s  {f'{called}/{total}':>16s}  {issued:>15d}")
    write_sensitivity_csv(sweep)

    daily = write_daily_csv(panels)
    summary = write_summary_csv(panels)
    print(f"\nWrote {daily.relative_to(HERE.parent.parent)}")
    print(f"Wrote {summary.relative_to(HERE.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
