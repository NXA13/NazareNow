"""Does the Predictive Distribution contain the sea that turned up?

Ticket #80. Every term in the distribution was measured — forecast drift by #14, the
Translation residual by #52 and #58, the Amplification Model's own error by #13 — and their
sum never was. This scores the assembled thing against outcomes, at each Lead Time, and
reports the two numbers a reader of the site actually rests on:

**The range in metres** (`interval_coverage.csv`). `PredictiveDistribution.range_m` is the
5th to 95th percentile of the draws, so it claims to hold the outcome 90% of the time. This
counts how often it did.

**The probability behind a Go Call** (`gate_reliability.csv`). `decide` withholds a Go Call
unless `height_bar_probability` reaches `GO_CALL_MINIMUM_HEIGHT_PROBABILITY`, which is 0.70.
That number is a share of `offshore_samples` clearing the calibrated height bar (#66), so it
is a forecast of an event that either happened or did not, and it can be scored the way any
probability is:
group the hours by what was predicted and count what happened.

**The real builder, not a copy.** `ErrorBudget.shipped()` and
`pipeline.amplification_model()` are imported and driven. `analysis/calibration/calibrate.py`
sets that precedent — "the real rule, not a copy" — and it binds harder here, where a
reimplementation would be re-deriving the arithmetic under test and would agree with itself
by construction.

## Three ways this is not the running system, two of which flatter it

A reader has to be able to place the result between "the site's ranges are honest" and "the
site's ranges are honest under conditions kinder than it runs in". These are the differences,
with their directions.

**Seven of eight features are settled, not forecast — flatters.** The Swell partition is not
archived at any Lead Time (ADR 0004's #14 amendment), which is why `distribution` leaves it
unperturbed in the first place, and this supplies Open-Meteo's own settled analysis for it.
The centre is therefore better placed than a Pipeline Run's would be. `settled.py` carries the
argument at length.

**No ensemble term — understates the width.** `_drift_floor` raises the drift to the
independent wave models' disagreement where that is larger, and it can only raise it. No
per-Lead-Time ensemble archive exists (`analysis/model_spread/` is explicit that its one live
sample must not be believed), so every distribution here is built with `model_spread=None`.
The builder's own docstring says the ensemble carries 0.263 m of sigma against 0.130 m of
big-swell drift at one day, and the archive overtakes it by six — so this omission bites hard
at short Lead Time and barely at long. It is the reason the table below must be read per Lead
Time and never collapsed into one figure.

**One partial Big-Wave Season — narrows what any of it can settle.** The wave archive opens
2025-11-16 and the Proxy Target join ends 2026-02-20, so the interval table rests on the same
1,593 hours as finding 3 of `analysis/forecast_error/README.md`. That is enough to catch an
interval that is half the width it should be. It is not enough to certify a tail, and no
figure here should be quoted as a calibration certificate.

The gate table does not need the buoy — its outcome is whether the settled Combined Sea
cleared the bar — so it runs on every archived hour that also carries a settled Swell
partition, which is the wider of the two joins by roughly four to one.

Run:
    .venv/Scripts/python.exe analysis/distribution_coverage/coverage.py

    # Re-checks the committed tables' arithmetic and joins, offline.
    .venv/Scripts/python.exe analysis/distribution_coverage/coverage.py --check
"""

from __future__ import annotations

import csv
import math
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "output"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from profile import BIG_SWELL_M, load_proxy_target, percentile  # noqa: E402

from download_runs import LEAD_TIMES, Runs, waves, wind  # noqa: E402
from nazarenow.distribution import ErrorBudget, PredictiveDistribution  # noqa: E402
from nazarenow.models.base import AmplificationModel  # noqa: E402
from nazarenow.pipeline import amplification_model  # noqa: E402
from nazarenow.thresholds import load as load_thresholds  # noqa: E402
from settled import settled  # noqa: E402

NOMINAL = 0.90
"""What `range_m` claims: the 5th to 95th percentile of the draws holds the outcome.

Written as one constant because it appears three times — the column a coverage is compared
against, the fraction the widening factor is read at, and the prose. Three literals would be
three places to update if `range_m` ever reported a different pair.
"""

PROBABILITY_BINS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
"""Deciles of predicted probability, the standard grouping for a reliability table.

The bin edges matter for one reason beyond convention: 0.70 is
`GO_CALL_MINIMUM_HEIGHT_PROBABILITY`, so it falls on an edge and the three bins above it are
exactly the hours a Go Call could have been issued on.
"""


@dataclass(frozen=True)
class Scored:
    """One hour at one Lead Time, after the shipped builder has had its say."""

    hour: str
    lead: int
    observed: float | None
    """The Proxy Target at Monican02. `None` for an hour the buoy did not report."""

    centre: float
    p5: float
    p95: float
    gate_probability: float
    gate_probability_drift_only: float
    """The same probability with the Translation residual taken out of the input spread.

    Not a proposed change — a control, and without it the gate table below is misleading.
    `height_bar_probability` forecasts "the sea clears the bar", and `offshore_samples` carry
    both terms: forecast drift, and the residual of the transform that put the bar into
    operational units in the first place (`thresholds.json`, `calibration.method`). The second
    is uncertainty about **where the bar is**, and comparing a reading to a bar is symmetric —
    it makes no arithmetical difference which side of the comparison carries it.

    But the *observable* event is a settled reading against the shipped bar, with the bar's own
    uncertainty absent from it. Scoring a probability that carries that term against an outcome
    that does not would read as under-confidence for a reason that is arithmetic rather than
    empirical. This column is the same probability with the term removed, so the two tables
    bracket the question instead of one of them answering it wrongly.
    """

    settled_sea: float
    """Open-Meteo's settled Combined Sea for the hour — the gate's outcome, and the regime
    the forecast is classified by when no Proxy Target exists to classify it."""


def readings_at(
    hour: str,
    lead: int,
    sea: Runs,
    winds: Runs,
    swell: dict[str, dict[str, float]],
) -> dict[str, float] | None:
    """The eight features as a Pipeline Run would hold them, or `None` if an hour is short.

    The Combined Sea is the **lead-N** forecast, because that is the one quantity the
    distribution perturbs and therefore the only one whose Lead Time changes the answer.
    Everything else is settled — see this module's header for why, and in which direction it
    moves the result.
    """
    forecast = sea.readings.get(hour, {}).get(lead, {}).get("wave_height")
    settled_wind = winds.readings.get(hour, {}).get(0, {})
    partition = swell.get(hour)
    if forecast is None or partition is None:
        return None
    if "wind_speed_10m" not in settled_wind or "wind_direction_10m" not in settled_wind:
        return None
    return {
        "significant_wave_height": float(forecast),
        "wind_speed": float(settled_wind["wind_speed_10m"]),
        "wind_direction": float(settled_wind["wind_direction_10m"]),
        **partition,
    }


def score(
    budget: ErrorBudget,
    model: AmplificationModel,
    sea: Runs,
    winds: Runs,
    swell: dict[str, dict[str, float]],
    observed: dict[str, float],
    height_bar_m: float,
) -> list[Scored]:
    """Build the shipped distribution for every archived hour at every Lead Time."""
    # The control described on `Scored.gate_probability_drift_only`. Built by replacing one
    # field of the shipped budget rather than by hand-rolling a second sampler, so the two
    # columns differ in exactly the term named and in nothing else.
    drift_only = replace(budget, translation_rmse=0.0)

    rows: list[Scored] = []
    for hour in sorted(swell):
        settled_sea = sea.readings.get(hour, {}).get(0, {}).get("wave_height")
        if settled_sea is None:
            continue
        for lead in LEAD_TIMES:
            features = readings_at(hour, lead, sea, winds, swell)
            if features is None:
                continue
            built = budget.distribution(model, features, lead, height_bar_m=height_bar_m)
            control = drift_only.distribution(model, features, lead, height_bar_m=height_bar_m)
            low, high = built.range_m
            rows.append(
                Scored(
                    hour=hour,
                    lead=lead,
                    observed=observed.get(hour),
                    centre=_median(built),
                    p5=low,
                    p95=high,
                    gate_probability=_required(built.height_bar_probability, hour, lead),
                    gate_probability_drift_only=_required(
                        control.height_bar_probability, hour, lead
                    ),
                    settled_sea=float(settled_sea),
                )
            )
    if not rows:
        raise RuntimeError("no archived hour carried all eight features at any Lead Time")
    return rows


def _median(built: PredictiveDistribution) -> float:
    """The distribution's centre, as the median draw rather than the mean.

    The samples are floored at zero on both the input and the output side, so the mean of a
    distribution reaching the floor sits above its middle. The median is what
    `range_m`'s percentiles are measured from and is the honest centre to score a miss
    against.
    """
    return statistics.median(built.samples)


def _required(probability: float | None, hour: str, lead: int) -> float:
    """`height_bar_probability`, refusing the `None` that would silently drop the gate table.

    It is `None` only when the builder was not told the bar. This module always tells it, so
    a `None` here means the argument stopped arriving — which would otherwise show up as an
    empty reliability table rather than as an error.
    """
    if probability is None:
        raise RuntimeError(
            f"{hour} at lead {lead}: the builder returned no height_bar_probability "
            "despite being given a bar"
        )
    return probability


@dataclass(frozen=True)
class Coverage:
    """How often the stated range held the outcome, at one Lead Time over one subset."""

    lead: int
    subset: str
    hours: int
    covered: float
    below: float
    above: float
    median_width_m: float
    median_normalised: float
    widening_factor: float

    @property
    def shortfall(self) -> float:
        """Nominal coverage minus measured. Positive means the range is too narrow."""
        return NOMINAL - self.covered


def cover(lead: int, subset: str, rows: list[Scored]) -> Coverage:
    """Collapse a Lead Time's scored hours into the coverage question and its shape.

    Three numbers rather than one, because "the range missed" has three repairs and the
    count alone does not distinguish them. `below` and `above` separate a range that is
    off-centre from one that is merely narrow: a narrow range misses about equally on both
    sides, a displaced one misses on one. `widening_factor` says how much wider the range
    would have to be to hold what it claims, in multiples of its own half-width, which is
    the form a repair would take.
    """
    outcomes = [row for row in rows if row.observed is not None]
    if not outcomes:
        raise ValueError(f"lead {lead} ({subset}): no hour carries a Proxy Target")

    below = sum(1 for row in outcomes if row.observed < row.p5)
    above = sum(1 for row in outcomes if row.observed > row.p95)
    normalised = [_normalised(row) for row in outcomes]

    return Coverage(
        lead=lead,
        subset=subset,
        hours=len(outcomes),
        covered=(len(outcomes) - below - above) / len(outcomes),
        below=below / len(outcomes),
        above=above / len(outcomes),
        median_width_m=statistics.median(row.p95 - row.p5 for row in outcomes),
        median_normalised=statistics.median(normalised),
        widening_factor=percentile([abs(value) for value in normalised], NOMINAL),
    )


def _normalised(row: Scored) -> float:
    """The miss, in multiples of the range's own half-width.

    A calibrated range puts 90% of these inside ±1 by construction, so the sample's own 90th
    percentile of `|normalised|` *is* the factor the range is out by — 2.0 means the stated
    range is half the width it should be. Expressing the miss this way rather than in metres
    is what lets Lead Times with very different widths be compared in one column.

    A zero-width range would make this undefined. That cannot arise from the shipped builder
    — every term is required positive, `forecast_error.parse` refuses a non-positive drift —
    so it raises rather than defending against a case that would mean the budget was empty.
    """
    half_width = (row.p95 - row.p5) / 2.0
    if half_width <= 0.0:
        raise ValueError(f"{row.hour} at lead {row.lead}: the stated range has no width")
    return (row.observed - row.centre) / half_width


@dataclass(frozen=True)
class Reliability:
    """One bin of a reliability table: what was promised against what happened."""

    lead: int
    terms: str
    low: float
    high: float
    hours: int
    mean_predicted: float
    observed_frequency: float


SHIPPED = "shipped"
DRIFT_ONLY = "drift only"


def reliability(
    lead: int, rows: list[Scored], height_bar_m: float, terms: str
) -> list[Reliability]:
    """Group a Lead Time's hours by predicted probability and count what happened.

    The event is the one the gate is about: the settled Combined Sea clearing the calibrated
    height bar. Not the Proxy Target — `height_bar_probability` is read off `offshore_samples`
    and the bar is fitted in operational units on the incoming reading (#66), so scoring it
    against the buoy would be asking a different question and would fail for a reason that had
    nothing to do with the gate.

    `terms` selects which of the two probabilities is being scored — see
    `Scored.gate_probability_drift_only` for why one number could not answer this on its own.
    """
    if terms == SHIPPED:
        predicted = lambda row: row.gate_probability  # noqa: E731
    elif terms == DRIFT_ONLY:
        predicted = lambda row: row.gate_probability_drift_only  # noqa: E731
    else:
        raise ValueError(f"{terms!r} is neither {SHIPPED!r} nor {DRIFT_ONLY!r}")

    bins = []
    for low, high in zip(PROBABILITY_BINS[:-1], PROBABILITY_BINS[1:], strict=True):
        # The top bin closes at 1.0 inclusive; every other is half-open, so an hour lands in
        # exactly one and a probability of exactly 1.0 is not silently dropped.
        top = high >= 1.0
        inside = [
            row for row in rows if low <= predicted(row) < high or (top and predicted(row) == high)
        ]
        if not inside:
            continue
        bins.append(
            Reliability(
                lead=lead,
                terms=terms,
                low=low,
                high=high,
                hours=len(inside),
                mean_predicted=statistics.fmean(predicted(row) for row in inside),
                observed_frequency=sum(1 for row in inside if row.settled_sea >= height_bar_m)
                / len(inside),
            )
        )
    return bins


def big_hours(rows: list[Scored]) -> set[str]:
    """The hours that *turned out* big, by the Proxy Target rather than by the forecast.

    `analysis/forecast_error/profile.py` states the principle this follows: a subset chosen
    on what the forecast said silently drops every big swell the forecast missed, which is
    the failure the subset exists to find. Here the reference available is the Proxy Target
    itself, so "big" means the buoy measured at least `BIG_SWELL_M`.
    """
    return {row.hour for row in rows if row.observed is not None and row.observed >= BIG_SWELL_M}


def write_coverage(rows: list[Coverage]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "interval_coverage.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "lead_days",
                "subset",
                "hours",
                "nominal",
                "covered",
                "below_p5",
                "above_p95",
                "median_width_m",
                "median_normalised",
                "widening_factor",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.lead,
                    row.subset,
                    row.hours,
                    NOMINAL,
                    round(row.covered, 4),
                    round(row.below, 4),
                    round(row.above, 4),
                    round(row.median_width_m, 4),
                    round(row.median_normalised, 4),
                    round(row.widening_factor, 4),
                ]
            )
    return path


def write_reliability(rows: list[Reliability]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "gate_reliability.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "lead_days",
                "terms",
                "bin_low",
                "bin_high",
                "hours",
                "mean_predicted",
                "observed_frequency",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.lead,
                    row.terms,
                    round(row.low, 2),
                    round(row.high, 2),
                    row.hours,
                    round(row.mean_predicted, 4),
                    round(row.observed_frequency, 4),
                ]
            )
    return path


def print_coverage(rows: list[Coverage], subset: str) -> None:
    print(f"\nInterval coverage — {subset}. Nominal {NOMINAL:.0%}.")
    print(
        f"{'Lead':<6}{'Hours':>8}{'Covered':>10}{'Below':>9}{'Above':>9}{'Width':>9}{'Factor':>9}"
    )
    for row in rows:
        if row.subset != subset:
            continue
        print(
            f"{row.lead}d{'':<4}{row.hours:>8,}{row.covered:>10.1%}{row.below:>9.1%}"
            f"{row.above:>9.1%}{row.median_width_m:>8.2f}m{row.widening_factor:>9.2f}"
        )


def print_reliability(rows: list[Reliability], lead: int, terms: str) -> None:
    print(f"\nGo Call gate reliability at {lead} days, {terms}. Predicted against observed.")
    print(f"{'Bin':<14}{'Hours':>9}{'Predicted':>12}{'Happened':>11}")
    for row in rows:
        if row.lead != lead or row.terms != terms:
            continue
        print(
            f"{row.low:.1f}-{row.high:.1f}{'':<7}{row.hours:>9,}"
            f"{row.mean_predicted:>12.3f}{row.observed_frequency:>11.3f}"
        )


def main() -> int:
    thresholds = load_thresholds()
    height_bar_m = thresholds.minimum_significant_wave_height_m
    budget = ErrorBudget.shipped()
    model = amplification_model()

    print(f"Scoring the shipped distribution: model {model.name}, height bar {height_bar_m} m")
    rows = score(budget, model, waves(), wind(), settled(), load_proxy_target(), height_bar_m)

    scored_hours = {row.hour for row in rows}
    with_target = {row.hour for row in rows if row.observed is not None}
    print(f"{len(scored_hours):,} archived hours scored, {len(with_target):,} carrying a target")

    big = big_hours(rows)
    coverage = []
    for lead in LEAD_TIMES:
        at_lead = [row for row in rows if row.lead == lead]
        coverage.append(cover(lead, "all hours", at_lead))
        big_at_lead = [row for row in at_lead if row.hour in big]
        if big_at_lead:
            coverage.append(cover(lead, "big swell", big_at_lead))

    gate = []
    for lead in LEAD_TIMES:
        at_lead = [row for row in rows if row.lead == lead]
        for terms in (SHIPPED, DRIFT_ONLY):
            gate.extend(reliability(lead, at_lead, height_bar_m, terms))

    print_coverage(coverage, "all hours")
    print_coverage(coverage, "big swell")
    for terms in (SHIPPED, DRIFT_ONLY):
        print_reliability(gate, 5, terms)

    print(f"\nWrote {write_coverage(coverage).relative_to(ROOT)}")
    print(f"Wrote {write_reliability(gate).relative_to(ROOT)}")
    return 0


def check() -> int:
    """Re-check the committed tables offline: the arithmetic, and the joins that would lie.

    Needs no archive, no network and no credentials — the same guarantee
    `analysis/track_record/publish.py --check` gives. What it cannot do is re-derive the
    distributions; that needs the archive. So this pins the properties a wrong table would
    break, not the values themselves.
    """
    failures: list[str] = []

    def expect(label: str, condition: bool, detail: str) -> None:
        if not condition:
            failures.append(f"{label}: {detail}")

    coverage_path = OUTPUT / "interval_coverage.csv"
    gate_path = OUTPUT / "gate_reliability.csv"
    for path in (coverage_path, gate_path):
        if not path.exists():
            print(f"{path.relative_to(ROOT)} is missing; run coverage.py first")
            return 1

    with coverage_path.open(newline="", encoding="utf-8") as handle:
        coverage = list(csv.DictReader(handle))
    with gate_path.open(newline="", encoding="utf-8") as handle:
        gate = list(csv.DictReader(handle))

    expect(
        "coverage leads",
        {int(row["lead_days"]) for row in coverage} == set(LEAD_TIMES),
        "the table does not cover exactly the archive's Lead Times",
    )

    for row in coverage:
        where = f"lead {row['lead_days']} ({row['subset']})"
        covered = float(row["covered"])
        below, above = float(row["below_p5"]), float(row["above_p95"])
        expect(
            f"{where} shares",
            math.isclose(covered + below + above, 1.0, abs_tol=5e-4),
            f"covered + below + above is {covered + below + above:.4f}, not 1",
        )
        expect(
            f"{where} nominal",
            math.isclose(float(row["nominal"]), NOMINAL),
            f"the table was written against a nominal of {row['nominal']}, not {NOMINAL}",
        )
        expect(
            f"{where} width",
            float(row["median_width_m"]) > 0.0,
            "a stated range with no width means the error budget was empty",
        )
        # The widening factor and the coverage are two readings of one fact, so they cannot
        # disagree about direction. A factor above 1 means the range did not reach 90%.
        expect(
            f"{where} factor agrees with coverage",
            (float(row["widening_factor"]) > 1.0) == (covered < NOMINAL),
            f"factor {row['widening_factor']} against coverage {covered:.4f}",
        )

    expect(
        "gate carries both term sets",
        {row["terms"] for row in gate} == {SHIPPED, DRIFT_ONLY},
        "one of the two columns is missing, so the table answers the gate question alone",
    )

    for row in gate:
        where = f"lead {row['lead_days']} {row['terms']} bin {row['bin_low']}-{row['bin_high']}"
        predicted = float(row["mean_predicted"])
        expect(
            f"{where} predicted in bin",
            float(row["bin_low"]) <= predicted <= float(row["bin_high"]),
            f"mean predicted {predicted} sits outside its own bin",
        )
        expect(
            f"{where} frequency",
            0.0 <= float(row["observed_frequency"]) <= 1.0,
            "an observed frequency outside [0, 1] is not a frequency",
        )

    # Every Lead Time must reach the bins a Go Call can be issued from, or the gate table
    # says nothing about the gate. Go Calls run to seven days (`decision.GO_CALL_THROUGH`).
    for lead in LEAD_TIMES:
        for terms in (SHIPPED, DRIFT_ONLY):
            expect(
                f"lead {lead} ({terms}) reaches the gate",
                any(
                    int(row["lead_days"]) == lead
                    and row["terms"] == terms
                    and float(row["bin_low"]) >= 0.7
                    for row in gate
                ),
                "no hour at this Lead Time was ever predicted at or above "
                "GO_CALL_MINIMUM_HEIGHT_PROBABILITY",
            )

    for failure in failures:
        print(f"FAIL {failure}")
    print(f"coverage.py --check: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv else main())
