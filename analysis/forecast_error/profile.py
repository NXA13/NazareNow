"""The Forecast Error Profile: how wrong the forecast is at each Lead Time.

Ticket #14, ADR 0004. The Amplification Model learns the physical relationship from clean
Hindcast inputs; forecast unreliability is characterised here, separately, so that #15 can
perturb an incoming forecast by a measured distribution rather than an assumed one.

**Two references, measuring two different things, and they must not be confused.**

`against_analysis` compares the lead-N forecast with Open-Meteo's own archived best match for
the same hour. That is **drift within one product**: how much the model changes its mind as
the date approaches, and nothing else. It is the quantity #15 injects, because the product's
standing offset from the Hindcast the model was fitted on is already handled by the
Translations in `amplification.json` — injecting a profile that contained it as well would
count the same error twice.

`against_target` compares the lead-N forecast with the **Proxy Target** measured at Monican02
over the hours the record covers. That is **total** error — drift, plus the product offset,
plus wherever the model sits relative to the buoy. It cannot be injected without
double-counting, and it is what answers #14's question about whether the provider is
systematically biased rather than merely noisy.

Both are reported on every run, side by side, because the interesting result is the gap
between them: at one day out the total is six times the drift.

Run:
    .venv/Scripts/python.exe analysis/forecast_error/profile.py
    .venv/Scripts/python.exe analysis/forecast_error/profile.py --check
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from download_runs import (  # noqa: E402
    LEAD_TIMES,
    WAVE_ARCHIVE_START,
    Runs,
    waves,
    wind,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

TRAINING_DATASET = ROOT / "analysis" / "training_dataset" / "output" / "training_dataset.csv"

BIG_SWELL_M = 3.0
"""The regime the system exists to call, matching `analysis/amplification_model/train.py`.

Defined on the *reference* rather than on the forecast, so the subset means "hours that
turned out big" rather than "hours the model said would be big". Those are different
questions and the second one flatters a model that under-forecasts: it would silently drop
every big swell the forecast missed, which is precisely the failure #14 exists to measure.
"""

CIRCULAR = ("wave_direction", "wind_direction_10m")
"""Variables in degrees, where 359° and 1° are two degrees apart, not 358.

Subtracting these as plain numbers is the classic way to produce a direction error that
looks enormous and is not. The Heuristic Baseline decides on swell direction, so an inflated
direction error would widen #15's injected distribution around a threshold the system
actually uses."""

UNITS = {
    "wave_height": "m",
    "wave_period": "s",
    "wave_direction": "°",
    "wind_speed_10m": "km/h",
    "wind_direction_10m": "°",
}


def angular_error(forecast: float, reference: float) -> float:
    """Signed difference between two bearings, wrapped into [-180, 180).

    Positive means the forecast was clockwise of what happened. The wrap is what stops a
    forecast of 002° against an outcome of 358° reporting a 356° miss instead of a 4° one.

    At exactly 180° apart the sign is arbitrary — clockwise and anticlockwise describe the
    same miss — and this returns -180. Nothing downstream depends on which: the magnitude
    is what the profile reports, and an exact antipode is a measure-zero case in a sample
    of thousands.
    """
    return (forecast - reference + 180.0) % 360.0 - 180.0


def error(variable: str, forecast: float, reference: float) -> float:
    """The forecast's miss, in the variable's own units and with its own arithmetic."""
    if variable in CIRCULAR:
        return angular_error(forecast, reference)
    return forecast - reference


def percentile(values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already-sorted-or-not list.

    Written out rather than taken from `statistics.quantiles`, which reports the *cut
    points between n groups* and cannot express an arbitrary fraction directly. The 5th and
    95th are what the README quotes as the range a Lead Time's error falls in, so the
    definition has to be one a reader can check by hand.
    """
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class Summary:
    """One variable's error distribution at one Lead Time."""

    variable: str
    lead: int
    subset: str
    hours: int
    bias: float
    mae: float
    rmse: float
    p5: float
    p95: float

    @property
    def drift(self) -> float:
        """The part of the error a constant correction cannot remove.

        Called `drift` and not `noise` since #65. CONTEXT.md's Forecast Error Profile entry
        puts "noise" on its _Avoid_ list and defines the quantity as how far a forecast
        *drifts*, which is also what `distribution.py` has always called it once past the
        boundary. One quantity carrying two names across a file boundary is the hazard; this
        is the name the domain already had.
        """
        return math.sqrt(max(self.rmse**2 - self.bias**2, 0.0))

    @property
    def bias_share(self) -> float:
        """Fraction of squared error a constant correction would remove.

        This is the number that answers "systematically biased, or merely noisy". A share
        near zero means the forecast is unbiased and simply uncertain, and there is nothing
        to correct — only a distribution to inject. A large share means the provider is
        reliably wrong in one direction, which is a correction #15 should apply *before*
        widening anything, because injecting spread around a displaced centre produces a
        confident distribution centred on the wrong answer.
        """
        if self.rmse == 0.0:
            return 0.0
        return self.bias**2 / self.rmse**2


def summarise(variable: str, lead: int, subset: str, errors: list[float]) -> Summary:
    """Collapse a Lead Time's misses into the distribution #15 will inject."""
    if not errors:
        raise ValueError(f"{variable} at lead {lead} ({subset}): no paired hours to summarise")
    return Summary(
        variable=variable,
        lead=lead,
        subset=subset,
        hours=len(errors),
        bias=statistics.fmean(errors),
        mae=statistics.fmean(abs(value) for value in errors),
        rmse=math.sqrt(statistics.fmean(value**2 for value in errors)),
        p5=percentile(errors, 0.05),
        p95=percentile(errors, 0.95),
    )


def load_proxy_target() -> dict[str, float]:
    """The Proxy Target by local hour, over the span the forecast archive reaches.

    Read straight from #9's dataset rather than re-derived, so the hours this profile calls
    "what happened" are byte-for-byte the hours the Amplification Model was fitted against.
    """
    if not TRAINING_DATASET.exists():
        raise SystemExit(
            f"{TRAINING_DATASET.relative_to(ROOT)} is missing. It is gitignored and rebuilt "
            "by:\n    .venv/Scripts/python.exe analysis/training_dataset/build.py"
        )
    first_archived_hour = WAVE_ARCHIVE_START.isoformat()
    observed: dict[str, float] = {}
    with TRAINING_DATASET.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            at = row["at_local"]
            if at < first_archived_hour:
                continue
            value = row["proxy_target_height_m"]
            if value:
                observed[at] = float(value)
    return observed


def against_analysis(runs: Runs, variable: str, sea: Runs) -> list[Summary]:
    """Drift within Open-Meteo: the lead-N forecast against its own day-0 best match.

    Both readings come out of the same cached response, so nothing here is our own sampling
    of the provider drifting between two calls.

    `sea` carries the day-0 Combined Sea that decides which hours were big, and is passed in
    rather than read off `runs` because **wind is archived on a different host**. Its
    responses hold no `wave_height` at all, so classifying wind hours from their own
    response is not merely inaccurate — it silently yields an empty subset, and wind error
    on big-swell hours is exactly what a Watch tier issued days out depends on.
    """
    big_hours = big_sea_hours(sea)

    summaries = []
    for lead in LEAD_TIMES:
        pairs = runs.pairs(variable, lead)
        errors = [error(variable, forecast, reference) for _, forecast, reference in pairs]
        if not errors:
            # A Lead Time the archive never answered for is absent from the table rather
            # than a row of zeroes. Reaching here means the retrieval is thinner than
            # `download_runs.py` believes, which the README's coverage column will show.
            continue
        summaries.append(summarise(variable, lead, "all hours", errors))

        big = [
            error(variable, forecast, reference)
            for hour, forecast, reference in pairs
            if hour in big_hours
        ]
        if big:
            summaries.append(summarise(variable, lead, "big swell", big))
    return summaries


def big_sea_hours(sea: Runs) -> set[str]:
    """The hours whose day-0 Combined Sea cleared the big-swell bar.

    Resolved once, from the source that actually carries wave height, and it **raises if
    that source carries none**. Deciding the subset hour by hour with a defaulting lookup is
    what let wind be classified from its own response: wind is archived on a different host
    and its readings hold no `wave_height`, so every hour defaulted to "not big", the subset
    came out empty, and an absent table is indistinguishable from a calm nine months.
    """
    hours = {
        hour
        for hour, by_lead in sea.readings.items()
        if by_lead.get(0, {}).get("wave_height", 0.0) >= BIG_SWELL_M
    }
    if not any("wave_height" in by_lead.get(0, {}) for by_lead in sea.readings.values()):
        raise ValueError(
            f"{sea.name} carries no day-0 wave_height, so the big-swell subset cannot be "
            "decided from it — pass the marine runs as `sea`"
        )
    return hours


def against_target(runs: Runs, observed: dict[str, float]) -> list[Summary]:
    """Total error: the lead-N forecast against the Proxy Target measured at Monican02.

    Only height. The dataset's period and direction columns are the offshore buoy's, and
    Open-Meteo's `wave_direction` is Combined Sea while the Heuristic Baseline's direction
    rule is written in Swell terms — CONTEXT.md holds those apart, and pairing them here
    because both are called "direction" would produce a bias figure on the wrong variable.
    """
    summaries = []
    for lead in LEAD_TIMES:
        errors, big = [], []
        for hour, by_lead in runs.readings.items():
            forecast = by_lead.get(lead, {}).get("wave_height")
            measured = observed.get(hour)
            if forecast is None or measured is None:
                continue
            miss = forecast - measured
            errors.append(miss)
            if measured >= BIG_SWELL_M:
                big.append(miss)
        if errors:
            summaries.append(summarise("wave_height", lead, "all hours", errors))
        if big:
            summaries.append(summarise("wave_height", lead, "big swell", big))
    return summaries


def stability(runs: Runs, variable: str) -> list[tuple[int, str, int, float]]:
    """Mean drift per calendar month at each Lead Time.

    The profile above assumes the day-0 best match is a *stable* reference — the same
    product answering at every Lead Time, so that a difference between them is the forecast
    changing its mind and not the provider changing model. That assumption is checkable, and
    it does not hold everywhere: `wind_speed_10m` at leads 5 and 6 runs several km/h high
    for seven consecutive months and is unbiased at leads 4 and 7 either side of it.

    A month-by-month table is what distinguishes the two explanations. A forecast that is
    genuinely worse at one Lead Time is wrong in both directions and averages out; a reference
    that switches model is wrong in one direction for as long as the switch is in place.
    """
    rows = []
    for lead in LEAD_TIMES:
        by_month: dict[str, list[float]] = {}
        for hour, forecast, reference in runs.pairs(variable, lead):
            by_month.setdefault(hour[:7], []).append(error(variable, forecast, reference))
        for month, errors in sorted(by_month.items()):
            rows.append((lead, month, len(errors), statistics.fmean(errors)))
    return rows


def write_stability_csv(blocks: dict[str, list[tuple[int, str, int, float]]]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "reference_stability.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["variable", "unit", "lead_time_days", "month", "hours", "mean_drift"])
        for variable, rows in blocks.items():
            for lead, month, hours, mean in rows:
                writer.writerow([variable, UNITS[variable], lead, month, hours, f"{mean:.4f}"])
    return path


def breaks_monotonicity(summaries: list[Summary]) -> list[int]:
    """Lead Times where error *shrinks* as the forecast reaches further ahead.

    ADR 0004's whole premise is that "forecast error grows with Lead Time". That is a claim
    about the world, and it is also the assumption that makes a day-0 reference usable: if
    the same product answers at every Lead Time, a longer one can only be more uncertain. A
    Lead Time where RMSE goes *down* falsifies one of the two, and the second is far likelier
    — the reference is not one product at that Lead Time.

    Preferred over any threshold on how large a bias has to be before it looks structural.
    A threshold would need a number nobody can defend; this needs only the ADR's own claim,
    and it flags exactly the Lead Times where the published profile cannot be trusted.
    """
    ordered = sorted(
        (row for row in summaries if row.subset == "all hours"), key=lambda row: row.lead
    )
    return [
        row.lead
        for previous, row in zip(ordered, ordered[1:], strict=False)
        if row.rmse < previous.rmse
    ]


def write_csv(rows: list[Summary], name: str, reference: str) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "variable",
                "unit",
                "reference",
                "lead_time_days",
                "subset",
                "hours",
                "bias",
                "mae",
                "rmse",
                "drift",
                "bias_share",
                "p5",
                "p95",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.variable,
                    UNITS[row.variable],
                    reference,
                    row.lead,
                    row.subset,
                    row.hours,
                    f"{row.bias:.4f}",
                    f"{row.mae:.4f}",
                    f"{row.rmse:.4f}",
                    f"{row.drift:.4f}",
                    f"{row.bias_share:.4f}",
                    f"{row.p5:.4f}",
                    f"{row.p95:.4f}",
                ]
            )
    return path


PROFILE_JSON = ROOT / "backend" / "src" / "nazarenow" / "forecast_error.json"
"""Where the running system reads this profile from (#15).

The same idiom `thresholds.json` and `amplification.json` already use: measurement happens
here, against archives the running system cannot reach, and ships as data the backend
validates on load. #15 perturbs an incoming forecast by these numbers, so they have to travel
with the release rather than be re-derived at serving time.
"""

INJECTABLE_VARIABLE = "wave_height"
"""The only variable exported, and the reason the others are not.

#15 builds a Predictive Distribution over Significant Wave Height. Wave period and direction
have measured drift too, and injecting them would mean perturbing inputs the Amplification
Model weights at a standardised coefficient of 0.09 or less against Combined Sea's 1.09
(`analysis/amplification_model/output/feature_reliance.csv`) — cost in complexity, nothing in
width. Wind is not exported for a second reason on top: its drift is measurable only to four
days, so exporting it would hand #15 a profile that runs out three days before this one does.
"""


def write_profile_json(drift: list[Summary]) -> Path:
    """Export the drift profile the backend injects, per Lead Time.

    **Drift, not total error against the buoy**, and the distinction decides whether #15 is
    right. Finding 1 in `README.md` sets it out: the product's standing offset from the
    Hindcast the model was fitted on is already removed by the Translations in
    `amplification.json`, so a profile measured against the Proxy Target would carry that
    offset a second time and #15 would inject it twice. What is wanted here is how much the
    forecast *moves* as the date approaches, which is what this reference measures.

    `drift` rather than `rmse` is the width, because it is the part of the error a constant
    correction cannot remove. At every Lead Time here the bias share is under 1%, so the two
    are nearly equal and the centre needs no correction — but exporting the field that stays
    correct if that ever stops being true is cheaper than exporting the one that does not.

    **This is one of three terms and the file says so.** The Translation residual and the
    Amplification Model's own error are the other two, both larger at short Lead Time, and
    both already recorded in `amplification.json`. `only_term` is written into the file so a
    consumer reading it cannot mistake the part for the whole — the failure Finding 1 names
    explicitly, which would make the distribution roughly three times too narrow exactly
    where a user is most likely to act on it.
    """
    rows = {
        (row.lead, row.subset): row
        for row in drift
        if row.variable == INJECTABLE_VARIABLE and row.subset in ("all hours", "big swell")
    }
    leads = sorted({lead for lead, _ in rows})
    if not leads:
        raise RuntimeError(
            f"no {INJECTABLE_VARIABLE} drift rows to export; the profile the backend reads "
            "would ship empty and #15 would silently fall back to no spread at all"
        )

    payload = {
        "quantity": "significant_wave_height_m",
        "reference": "open-meteo day 0",
        "measured_through_lead_days": max(leads),
        "only_term": (
            "Forecast drift alone. The Translation residual and the Amplification Model's "
            "own error are the other two terms and are larger at short Lead Time; see "
            "analysis/forecast_error/README.md, Finding 1. A distribution built from this "
            "field alone is roughly three times too narrow at one day out."
        ),
        "by_lead_time": {
            str(lead): {
                "all_hours": _term(rows[(lead, "all hours")]),
                "big_swell": _term(rows[(lead, "big swell")]),
            }
            for lead in leads
            if (lead, "all hours") in rows and (lead, "big swell") in rows
        },
        "method": {
            "ticket": 14,
            "serves": 15,
            "archive_begins": f"{WAVE_ARCHIVE_START:%Y-%m-%d}",
            "big_swell_m": BIG_SWELL_M,
            "source": "analysis/forecast_error/profile.py",
        },
    }
    PROFILE_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return PROFILE_JSON


def _term(row: Summary) -> dict[str, float | int]:
    """One Lead Time's injectable width, rounded to where the measurement is real.

    Four decimals on a metre is a tenth of a millimetre of sea, which no archive resolves.
    It is kept because these are variances that get added in quadrature downstream, and
    rounding before squaring is how a width acquires a bias nobody can trace.
    """
    return {
        "drift": round(row.drift, 4),
        "bias": round(row.bias, 4),
        "p5": round(row.p5, 4),
        "p95": round(row.p95, 4),
        "hours": row.hours,
    }


def print_table(title: str, rows: list[Summary], subset: str) -> None:
    chosen = [row for row in rows if row.subset == subset]
    if not chosen:
        return
    print(f"\n{title} — {subset}\n")
    print(
        f"  {'variable':16s} {'lead':>5s} {'hours':>7s} {'bias':>9s} {'MAE':>9s} "
        f"{'RMSE':>9s} {'drift':>9s} {'bias share':>11s} {'5-95%':>19s}"
    )
    for row in chosen:
        print(
            f"  {row.variable:16s} {row.lead:5d} {row.hours:7d} {row.bias:9.3f} "
            f"{row.mae:9.3f} {row.rmse:9.3f} {row.drift:9.3f} {row.bias_share:10.1%} "
            f"{row.p5:9.2f} {row.p95:8.2f}"
        )


def check() -> int:
    """Self-test the arithmetic offline, per the root README's convention.

    What is worth checking is everything that turns readings into the distribution #15 will
    inject, because each is easy to write plausibly and wrong, and a wrong one would widen
    or narrow the system's stated confidence with nothing to contradict it.
    """
    failures: list[str] = []

    def expect_close(label: str, got: float, want: float, tolerance: float = 1e-9) -> None:
        if abs(got - want) > tolerance:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    # --- circular arithmetic ------------------------------------------------------------
    # The whole reason `CIRCULAR` exists. Subtracted as plain numbers the first of these
    # reports -356 instead of 4, which would make direction look like the least reliable
    # variable in the profile by two orders of magnitude.
    expect_close("a forecast just clockwise of north", angular_error(2.0, 358.0), 4.0)
    expect_close("a forecast just anticlockwise of north", angular_error(358.0, 2.0), -4.0)
    expect_close("no error is no error", angular_error(180.0, 180.0), 0.0)
    expect_close("opposite bearings are 180 apart", abs(angular_error(0.0, 180.0)), 180.0)
    expect_close("and the antipode never exceeds 180", abs(angular_error(180.0, 0.0)), 180.0)
    expect_close("the wrap has no seam at 360", angular_error(360.0, 0.0), 0.0)

    expect_close("height error is plain subtraction", error("wave_height", 4.0, 3.0), 1.0)
    expect_close("direction error is not", error("wave_direction", 2.0, 358.0), 4.0)
    expect_close("wind direction wraps too", error("wind_direction_10m", 350.0, 10.0), -20.0)

    # --- percentiles --------------------------------------------------------------------
    expect_close("the median of a symmetric sample", percentile([1.0, 2.0, 3.0], 0.5), 2.0)
    expect_close("the minimum", percentile([1.0, 2.0, 3.0], 0.0), 1.0)
    expect_close("the maximum", percentile([1.0, 2.0, 3.0], 1.0), 3.0)
    expect_close("interpolated between samples", percentile([0.0, 10.0], 0.25), 2.5)
    expect_close("order does not matter", percentile([3.0, 1.0, 2.0], 0.5), 2.0)

    try:
        percentile([], 0.5)
    except ValueError:
        pass
    else:
        failures.append("percentile: expected a ValueError on an empty sample")

    # --- the summary, and the decomposition #14 is asked for ----------------------------
    # A forecast that is always exactly half a metre high: all bias, no drift. If
    # `bias_share` did not report ~100% here, "systematically biased" would be
    # indistinguishable from "noisy" in the published table.
    biased = summarise("wave_height", 3, "all hours", [0.5] * 20)
    expect_close("a constant offset is all bias", biased.bias, 0.5)
    expect_close("a constant offset has no drift", biased.drift, 0.0)
    expect_close("a constant offset is fully correctable", biased.bias_share, 1.0)

    # A forecast wrong by half a metre in both directions equally: no bias, all drift. A
    # correction would achieve nothing, and MAE and RMSE agree only because every miss is
    # the same size.
    noisy = summarise("wave_height", 3, "all hours", [0.5, -0.5] * 10)
    expect_close("symmetric misses cancel in the bias", noisy.bias, 0.0)
    expect_close("but not in the MAE", noisy.mae, 0.5)
    expect_close("drift carries the whole error", noisy.drift, 0.5)
    expect_close("nothing here is correctable", noisy.bias_share, 0.0)

    # The decomposition has to hold for a sample that is neither, or the published
    # bias/drift split is arithmetic that only happens to work on tidy inputs.
    mixed = summarise("wave_height", 5, "all hours", [1.0, 0.0, 2.0, -1.0])
    expect_close("bias is the mean miss", mixed.bias, 0.5)
    expect_close("mae is the mean absolute miss", mixed.mae, 1.0)
    expect_close("rmse squares before averaging", mixed.rmse, math.sqrt(1.5))
    expect_close(
        "rmse squared is bias squared plus drift squared",
        mixed.bias**2 + mixed.drift**2,
        mixed.rmse**2,
    )

    try:
        summarise("wave_height", 1, "big swell", [])
    except ValueError:
        pass
    else:
        failures.append("summarise: expected a ValueError with no paired hours")

    # --- pairing ------------------------------------------------------------------------
    # An hour the archive answered at day 0 but not at lead 3 must drop out of both sides
    # of the difference. Carried through as a null it would become a 0.0 and report a
    # perfect forecast for an hour that was never forecast at all.
    runs = Runs(
        name="test",
        readings={
            "2026-01-01T00:00": {0: {"wave_height": 3.0}, 3: {"wave_height": 3.4}},
            "2026-01-01T01:00": {0: {"wave_height": 3.1}},
            "2026-01-01T02:00": {3: {"wave_height": 2.9}},
        },
    )
    paired = runs.pairs("wave_height", 3)
    if [hour for hour, _, _ in paired] != ["2026-01-01T00:00"]:
        failures.append(f"pairs: expected only the hour present at both leads, got {paired}")

    # The big-swell subset is chosen on the reference, not the forecast. Here the forecast
    # says 3.2 m and the sea was 2.0 m: an hour that must NOT count as big swell, or the
    # subset would quietly become "hours the model thought were big".
    subset_runs = Runs(
        name="test",
        readings={
            "2026-01-01T00:00": {0: {"wave_height": 2.0}, 1: {"wave_height": 3.2}},
            "2026-01-01T01:00": {0: {"wave_height": 4.0}, 1: {"wave_height": 3.5}},
        },
    )
    big = [
        row
        for row in against_analysis(subset_runs, "wave_height", sea=subset_runs)
        if row.subset == "big swell"
    ]
    if len(big) != 1 or big[0].hours != 1:
        failures.append(
            "against_analysis: the big-swell subset must be chosen on the reference, "
            f"got {[(row.subset, row.hours) for row in big]}"
        )
    else:
        expect_close("the big-swell hour is the one that was big", big[0].bias, -0.5)

    # A variable archived on a host that carries no wave height — wind — must still get a
    # big-swell subset, decided from the marine runs passed as `sea`. This shipped wrong:
    # a defaulting lookup classified every wind hour as small, the subset came out empty,
    # and an absent table read exactly like a calm nine months. Both review axes found it.
    off_host = Runs(
        name="wind",
        readings={
            "2026-01-01T00:00": {0: {"wind_speed_10m": 20.0}, 1: {"wind_speed_10m": 26.0}},
            "2026-01-01T01:00": {0: {"wind_speed_10m": 18.0}, 1: {"wind_speed_10m": 19.0}},
        },
    )
    off_host_sea = Runs(
        name="marine",
        readings={
            "2026-01-01T00:00": {0: {"wave_height": 4.0}},
            "2026-01-01T01:00": {0: {"wave_height": 1.0}},
        },
    )
    windy = [
        row
        for row in against_analysis(off_host, "wind_speed_10m", sea=off_host_sea)
        if row.subset == "big swell"
    ]
    if len(windy) != 1 or windy[0].hours != 1:
        failures.append(
            "against_analysis: a variable archived on another host must still get a "
            f"big-swell subset from `sea`, got {[(row.subset, row.hours) for row in windy]}"
        )
    else:
        expect_close("the big wind hour is the one with the big sea", windy[0].bias, 6.0)

    # And passing the wrong `sea` must fail loudly rather than yield an empty subset,
    # which is the shape the original bug took.
    try:
        big_sea_hours(off_host)
    except ValueError:
        pass
    else:
        failures.append("big_sea_hours: a source with no wave_height must raise, not return {}")

    # --- the reference-stability flag ---------------------------------------------------
    # A profile whose error grows every day is the shape ADR 0004 assumes and must pass
    # clean; one that gets *better* further out has a reference problem and must be named.
    # Getting this backwards would either bury the wind anomaly or condemn every honestly
    # noisy Lead Time alongside it.
    def rows(rmses: list[float], subset: str = "all hours") -> list[Summary]:
        return [
            Summary(
                variable="wind_speed_10m",
                lead=lead,
                subset=subset,
                hours=100,
                bias=0.0,
                mae=value,
                rmse=value,
                p5=-value,
                p95=value,
            )
            for lead, value in enumerate(rmses, start=1)
        ]

    if breaks_monotonicity(rows([3.2, 4.2, 5.0, 6.5, 8.0, 9.1, 10.4])) != []:
        failures.append("breaks_monotonicity: a profile that widens every day is the clean case")
    if breaks_monotonicity(rows([3.2, 4.2, 5.0, 6.5, 9.7, 10.7, 9.5])) != [7]:
        failures.append("breaks_monotonicity: a Lead Time whose RMSE falls must be flagged")

    # The big-swell subset has its own, smaller sample and its own RMSEs. Mixing the two
    # orderings would compare a big-swell lead against an all-hours one and flag noise.
    mixed_subsets = rows([3.2, 4.2, 5.0, 6.5, 8.0, 9.1, 10.4]) + rows(
        [9.0, 1.0, 9.0, 1.0, 9.0, 1.0, 9.0], subset="big swell"
    )
    if breaks_monotonicity(mixed_subsets) != []:
        failures.append("breaks_monotonicity: the big-swell rows must not enter the ordering")

    for failure in failures:
        print(f"FAIL {failure}")
    print("profile.py --check: " + ("FAILED" if failures else "all checks passed"))
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    wave_runs = waves()
    wind_runs = wind()
    observed = load_proxy_target()

    drift: list[Summary] = []
    for variable in ("wave_height", "wave_period", "wave_direction"):
        drift.extend(against_analysis(wave_runs, variable, sea=wave_runs))
    for variable in ("wind_speed_10m", "wind_direction_10m"):
        # `sea` is the marine runs even here: "big swell" is a property of the sea, not of
        # the variable being measured, and wind's own host carries no wave height.
        drift.extend(against_analysis(wind_runs, variable, sea=wave_runs))

    total = against_target(wave_runs, observed)

    print(
        f"Forecast Error Profile, {WAVE_ARCHIVE_START:%Y-%m-%d} onward — "
        f"{len(wave_runs)} archived hours, {len(observed)} of them with a Proxy Target."
    )
    # The Proxy Target stops well before the archive does, and the total-error tables are
    # bounded by it rather than by the retrieval. Printed rather than left to be inferred
    # from a row count: the two references are measured over different spans, and a reader
    # comparing them needs to know that before comparing them.
    print(
        f"  The Proxy Target runs {min(observed)} to {max(observed)}, ending where #9's "
        "dataset ends — every total-error figure below is bounded by that, not by the "
        "archive."
    )

    print_table("Drift within Open-Meteo (lead N against its own day 0)", drift, "all hours")
    print_table("Drift within Open-Meteo (lead N against its own day 0)", drift, "big swell")
    print_table("Total error against the Proxy Target at Monican02", total, "all hours")
    print_table("Total error against the Proxy Target at Monican02", total, "big swell")

    blocks = {
        "wave_height": stability(wave_runs, "wave_height"),
        "wave_period": stability(wave_runs, "wave_period"),
        "wind_speed_10m": stability(wind_runs, "wind_speed_10m"),
    }

    print("\nDoes error grow with Lead Time, as ADR 0004 assumes?\n")
    for variable in blocks:
        flagged = breaks_monotonicity([row for row in drift if row.variable == variable])
        if flagged:
            leads = ", ".join(str(lead) for lead in flagged)
            print(
                f"  {variable:16s} NO — RMSE falls at lead {leads}. The day-0 reference is "
                "not one product at every Lead Time here; see reference_stability.csv for "
                "the months. Not injectable as measured."
            )
        else:
            print(f"  {variable:16s} yes — RMSE rises at every Lead Time")

    drift_path = write_csv(drift, "drift_by_lead_time.csv", "open-meteo day 0")
    total_path = write_csv(total, "total_error_by_lead_time.csv", "proxy target")
    stability_path = write_stability_csv(blocks)
    profile_path = write_profile_json(drift)
    print(f"\nWrote {drift_path.relative_to(ROOT)}")
    print(f"Wrote {total_path.relative_to(ROOT)}")
    print(f"Wrote {stability_path.relative_to(ROOT)}")
    print(f"Wrote {profile_path.relative_to(ROOT)}  — the profile #15 injects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
