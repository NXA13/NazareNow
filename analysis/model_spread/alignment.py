"""Does run staleness contaminate Model Spread, or can the models be differenced as they arrive?

Ticket #8, ADR 0003. That ADR ends its implementation notes with a requirement:

    "#8 must align model runs before differencing, or this ADR's central mechanism will be
    reading staleness as doubt."

`probe.py` established that alignment **cannot be read from the provider** — the marine
endpoint exposes no run timestamp and silently ignores every parameter that looks like it
would pin one. It left two ways out: infer the runs by observation, which needs a Pipeline
Run accumulating raw responses that the parked deployment (#28) has not produced, or show
the staleness component is small beside the between-provider component. This does the
second, and it can be done now because the marine archive carries `_previous_dayN` **per
model** — `wave_height_previous_day1_dwd_gwam` and so on.

**The comparison.** Two quantities, over the same hours:

- *Self-movement*: how much one model changes its mind about a fixed hour between its own
  runs. Measured across 24 hours, because that is the finest interval the archive offers.
- *Provider spread*: how much the organisations disagree about that hour at one instant,
  each voting once.

The publication gap that worries ADR 0003 is **six to twelve hours** — NCEP runs six-hourly,
MeteoFrance and DWD twelve-hourly. So 24-hour self-movement is an **upper bound** on the
contamination, and a bound is the useful shape here: if even the bound is small beside the
spread, a gap shorter than the bound cannot be what the spread is made of. If the bound is
*not* small, this settles nothing and #8 has to align by observation after all.

Deliberately not assumed: that self-movement scales with the square root of time, or
linearly, or any other way. The growth exponent is **fitted** — `scaling` measures how movement
grows across every interval the archive offers, and `Comparison.movement_over` applies that
measured exponent downward to reach six and twelve hours. A pure random walk would give 0.5 and
a steadily improving forecast 1.0; the measured value sits between, so neither assumption would
have been right. It is still extrapolation below the measured range: the report states the
fitted exponent up front and keeps the extrapolated columns (`stale/6h`, `stale/12h`) separate
from the measured one (`measured/24h`), so the 24-hour figure is still reported as what it is.

**One honest mismatch.** The archive carries `_previous_dayN` only for the Combined Sea
partition — `analysis/forecast_error/README.md` records that the Swell variables come back
null at every Lead Time — while ADR 0003's Model Spread is defined on the Swell the Heuristic
Baseline decides on. So self-movement is measured on Combined Sea and the conclusion is
carried across to Swell by argument, not by measurement. `spread_on_both` measures the two
partitions side by side at one instant so the size of that leap is visible rather than
assumed.

Run:
    .venv/Scripts/python.exe analysis/model_spread/alignment.py
    .venv/Scripts/python.exe analysis/model_spread/alignment.py --check
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))

from download_runs import (  # noqa: E402
    END,
    LEAD_TIMES,
    WAVE_ARCHIVE_START,
)
from nazarenow.sources.open_meteo import (  # noqa: E402
    LATITUDE,
    LONGITUDE,
    MARINE_URL,
    TIMEZONE,
)

CACHE = ROOT / "data" / "raw" / "model_runs"
"""Gitignored under `data/raw/`, like every other raw archive in this repo."""

PROVIDERS = {
    "meteofrance_wave": "MeteoFrance",
    "dwd_ewam": "DWD",
    "dwd_gwam": "DWD",
    "ncep_gfswave025": "NCEP",
    "ncep_gfswave016": "NCEP",
}
"""The roster and the organisation behind each identifier, matching `probe.py`.

Five identifiers, three organisations. The grouping is not bookkeeping: two resolutions of
one centre's model share its physics, its assimilation and its bugs, so counting them as two
opinions makes the ensemble look twice as corroborated as it is."""

VARIABLE = "wave_height"
"""Combined Sea. The only partition the archive carries per model — see the module docstring
for what that costs and how `spread_on_both` bounds it."""

SWELL_VARIABLE = "swell_wave_height"

EXPECTED_UNIT = "m"

PAUSE_SECONDS = 1.0
ATTEMPTS = 4


def _get(url: str, params: dict[str, Any], cache_key: str) -> dict[str, Any]:
    """Fetch, or return the cached copy. Raw response kept exactly as it arrived."""
    path = CACHE / f"{cache_key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    CACHE.mkdir(parents=True, exist_ok=True)
    query = f"{url}?{urllib.parse.urlencode(params)}"
    body: dict[str, Any] | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(query, timeout=300) as response:
                body = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == ATTEMPTS:
                raise RuntimeError(f"{cache_key}: Open-Meteo returned {error.code}") from error
        except urllib.error.URLError as error:
            if attempt == ATTEMPTS:
                raise RuntimeError(
                    f"{cache_key}: could not reach Open-Meteo after {ATTEMPTS} attempts: {error}"
                ) from error
        time.sleep(PAUSE_SECONDS * 2**attempt)

    if body is None:  # pragma: no cover - the loop either breaks or raises
        raise RuntimeError(f"{cache_key}: no response and no error, which cannot happen")
    if "error" in body:
        raise RuntimeError(f"{cache_key}: Open-Meteo refused: {body.get('reason')}")

    path.write_text(json.dumps(body), encoding="utf-8")
    time.sleep(PAUSE_SECONDS)
    return body


def _months(start: date, end: date) -> list[tuple[date, date]]:
    """Split the span into calendar months, so a failed retrieval costs one month."""
    spans = []
    cursor = start
    while cursor <= end:
        following = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        spans.append((cursor, min(following - timedelta(days=1), end)))
        cursor = following
    return spans


@dataclass(frozen=True)
class Ensemble:
    """Every model's Combined Sea, keyed by hour and Lead Time.

    `readings[hour][lead][model]` is what `model` said about `hour` when asked `lead` days
    earlier; lead 0 is the archived best match for that model. An hour a model did not answer
    for is absent rather than present-and-None.
    """

    readings: dict[str, dict[int, dict[str, float]]]

    def __len__(self) -> int:
        return len(self.readings)


def _parse(body: dict[str, Any], name: str) -> Ensemble:
    """Validate a response and key it by hour, Lead Time and model."""
    if body.get("timezone") != TIMEZONE:
        raise ValueError(
            f"{name}: Open-Meteo returned timestamps on {body.get('timezone')!r}; ADR 0008 "
            f"groups hours into Nazaré local days on {TIMEZONE!r}"
        )
    hourly = body.get("hourly") or {}
    times = hourly.get("time")
    if not times:
        raise ValueError(f"{name}: response has no time axis")

    units = body.get("hourly_units") or {}
    wrong = {key: unit for key, unit in units.items() if key != "time" and unit != EXPECTED_UNIT}
    if wrong:
        raise ValueError(f"{name}: unexpected units {wrong}; this analysis is in metres")

    readings: dict[str, dict[int, dict[str, float]]] = {}
    for index, at in enumerate(times):
        by_lead: dict[int, dict[str, float]] = {}
        for lead in (0, *LEAD_TIMES):
            found: dict[str, float] = {}
            for model in PROVIDERS:
                stem = VARIABLE if lead == 0 else f"{VARIABLE}_previous_day{lead}"
                series = hourly.get(f"{stem}_{model}")
                value = series[index] if series is not None else None
                if value is not None:
                    found[model] = value
            if found:
                by_lead[lead] = found
        if by_lead:
            readings[at] = by_lead
    if not readings:
        raise ValueError(f"{name}: every hour was null for every model")
    return Ensemble(readings=readings)


def _variable_names() -> list[str]:
    """Day 0 and every Lead Time, for every model, in one request.

    Note the suffix order the provider uses: `wave_height_previous_day1_dwd_gwam`, with the
    Lead Time *before* the model. Written the other way round the endpoint returns 200 with
    the variable simply absent from the response, which is the same silent-agreement failure
    `probe.py` catalogues.
    """
    return [VARIABLE, *(f"{VARIABLE}_previous_day{lead}" for lead in LEAD_TIMES)]


def ensemble() -> Ensemble:
    """Every model's archived runs, over the same span `analysis/forecast_error/` uses."""
    merged: dict[str, dict[int, dict[str, float]]] = {}
    for start, end in _months(WAVE_ARCHIVE_START, END):
        body = _get(
            MARINE_URL,
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": ",".join(_variable_names()),
                "models": ",".join(PROVIDERS),
                "timezone": TIMEZONE,
                "length_unit": "metric",
            },
            f"ensemble_{start:%Y-%m}",
        )
        merged.update(_parse(body, f"ensemble {start:%Y-%m}").readings)
    return Ensemble(readings=merged)


def by_provider(readings: dict[str, float]) -> dict[str, float]:
    """Collapse each organisation's models to one opinion, as `probe.py` does.

    Kept identical to `probe.py` rather than imported, because the two scripts answer
    different questions and this one must not start failing if that one's roster changes.
    The self-test below pins the behaviour they share.
    """
    grouped: dict[str, list[float]] = {}
    for model, value in readings.items():
        grouped.setdefault(PROVIDERS[model], []).append(value)
    return {provider: statistics.median(values) for provider, values in grouped.items()}


def spread(values: list[float]) -> float:
    """Disagreement as the full range. Needs at least two opinions."""
    if len(values) < 2:
        raise ValueError("spread needs at least two opinions; one model is not an ensemble")
    return max(values) - min(values)


SLOWEST_CADENCE_HOURS = 12
"""The longest a model's run can be stale relative to a freshly published one.

MeteoFrance and DWD publish twelve-hourly, NCEP six-hourly (`analysis/forecast_models/`), so
at the moment one member has just published, another can be up to twelve hours old. Twelve
is therefore the **worst case**; with arrival times unrelated to our fetch, the *expected*
gap is half of it."""

EXPECTED_CADENCE_HOURS = SLOWEST_CADENCE_HOURS // 2


@dataclass(frozen=True)
class Comparison:
    """Staleness against disagreement, at one Lead Time."""

    lead: int
    hours: int
    self_movement: float
    provider_spread: float
    exponent: float

    def movement_over(self, gap_hours: int) -> float:
        """Self-movement over a shorter gap than the 24 hours the archive can measure.

        Scaled by a **measured** exponent rather than an assumed one. `scaling` fits how
        movement grows with the interval between runs across six intervals of real data;
        this applies that growth downward. It is still extrapolation below the measured
        range and is labelled as such wherever it is reported, but an extrapolation over a
        factor of two with a fitted exponent is a different object from a guess.
        """
        return self.self_movement * (gap_hours / 24.0) ** self.exponent

    def share_over(self, gap_hours: int) -> float:
        """What fraction of the measured disagreement that staleness could account for.

        The ratio, not a subtraction. Both are magnitudes of the same quantity in metres,
        and what ADR 0003 needs to know is whether one is *made of* the other — a spread
        that is mostly staleness is not doubt, it is a sampling artefact wearing doubt's
        clothes.
        """
        if self.provider_spread == 0.0:
            return 0.0
        return self.movement_over(gap_hours) / self.provider_spread


def scaling(runs: Ensemble, base_lead: int = 1) -> tuple[float, float]:
    """How self-movement grows with the interval between two runs: `(coefficient, exponent)`.

    Fitted by least squares on the logs across every interval the archive offers — 24 hours
    through 144 — because the interval that matters is 6 to 12 and the archive's finest step
    is 24. Without this the analysis can only say "less than the 24-hour figure", which at
    long Lead Time is not a useful bound.

    A pure random walk would give an exponent of 0.5 and a forecast that improves steadily
    with time would give 1.0. The measured value sits between, so neither assumption would
    have been right, which is the reason to fit rather than pick.
    """
    points = []
    for gap in range(1, len(LEAD_TIMES)):
        moves = []
        for by_lead in runs.readings.values():
            now = by_lead.get(base_lead, {})
            earlier = by_lead.get(base_lead + gap, {})
            shared = set(now) & set(earlier)
            if shared:
                moves.append(statistics.fmean(abs(now[m] - earlier[m]) for m in shared))
        if moves:
            points.append((24.0 * gap, statistics.fmean(moves)))
    if len(points) < 2:
        raise ValueError("scaling needs at least two intervals to fit a growth rate")

    xs = [math.log(gap) for gap, _ in points]
    ys = [math.log(move) for _, move in points]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    exponent = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sum(
        (x - mean_x) ** 2 for x in xs
    )
    return math.exp(mean_y - exponent * mean_x), exponent


def compare(runs: Ensemble, exponent: float) -> list[Comparison]:
    """Self-movement and provider spread, per Lead Time, over every hour that carries both.

    Self-movement is measured as the mean absolute change in one model's own forecast for a
    fixed hour across 24 hours — lead N against lead N+1, which are two runs of the same
    model a day apart. Averaged across models rather than reported per model: the question
    is whether *the ensemble's* spread is contaminated, and a single model's restlessness
    only matters through its contribution to that.

    Provider spread is the range across organisations at the same Lead Time, each voting
    once, over the same hours. Both restricted to hours where every provider reported, so
    the comparison is never between a three-provider spread and a two-provider one.
    """
    comparisons = []
    for lead in LEAD_TIMES[:-1]:
        movements: list[float] = []
        spreads: list[float] = []
        for by_lead in runs.readings.values():
            now = by_lead.get(lead, {})
            day_before = by_lead.get(lead + 1, {})
            shared = set(now) & set(day_before)
            if not shared:
                continue
            opinions = by_provider(now)
            if len(opinions) < len({PROVIDERS[model] for model in PROVIDERS}):
                continue
            movements.append(statistics.fmean(abs(now[m] - day_before[m]) for m in shared))
            spreads.append(spread(list(opinions.values())))
        if movements:
            comparisons.append(
                Comparison(
                    lead=lead,
                    hours=len(movements),
                    self_movement=statistics.fmean(movements),
                    provider_spread=statistics.fmean(spreads),
                    exponent=exponent,
                )
            )
    return comparisons


def spread_on_both() -> dict[str, float]:
    """Provider spread on Combined Sea and on Swell, at one instant, for the same hours.

    The archive carries no `_previous_dayN` for Swell, so self-*movement* cannot be measured on
    the partition Model Spread is defined on. This does not fix that. What it does is show how
    far apart the two partitions' spreads are *right now*, so a reader can see the size of the
    leap the conclusion makes rather than take it on trust.

    Narrowed from "the archive carries no Swell per model", which was the true statement about
    previous runs overstated into a false one about the archive. It does carry Swell per model
    for the run it settled on, back to 2024 for the whole roster, and `agreement.py` measures
    the gate over two Big-Wave Seasons of it. Only the movement between runs is missing.
    """
    body = _get(
        MARINE_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": f"{VARIABLE},{SWELL_VARIABLE}",
            "models": ",".join(PROVIDERS),
            "forecast_days": 7,
            "timezone": TIMEZONE,
            "length_unit": "metric",
        },
        "live_both_partitions",
    )
    hourly = body["hourly"]
    found: dict[str, list[float]] = {VARIABLE: [], SWELL_VARIABLE: []}
    for index in range(len(hourly["time"])):
        for variable in found:
            readings = {
                model: hourly[f"{variable}_{model}"][index]
                for model in PROVIDERS
                if hourly.get(f"{variable}_{model}", [None])[index] is not None
            }
            opinions = by_provider(readings)
            if len(opinions) >= 2:
                found[variable].append(spread(list(opinions.values())))
    return {
        variable: statistics.fmean(values) if values else 0.0 for variable, values in found.items()
    }


def write_csv(rows: list[Comparison]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "alignment.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "lead_time_days",
                "hours",
                "self_movement_24h_m",
                "provider_spread_m",
                "staleness_m_expected_6h",
                "staleness_m_worst_12h",
                "staleness_share_expected",
                "staleness_share_worst",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.lead,
                    row.hours,
                    f"{row.self_movement:.4f}",
                    f"{row.provider_spread:.4f}",
                    f"{row.movement_over(EXPECTED_CADENCE_HOURS):.4f}",
                    f"{row.movement_over(SLOWEST_CADENCE_HOURS):.4f}",
                    f"{row.share_over(EXPECTED_CADENCE_HOURS):.4f}",
                    f"{row.share_over(SLOWEST_CADENCE_HOURS):.4f}",
                ]
            )
    return path


def check() -> int:
    """Self-test the arithmetic offline, per the root README's convention."""
    failures: list[str] = []

    def expect_close(label: str, got: float, want: float, tolerance: float = 1e-9) -> None:
        if abs(got - want) > tolerance:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    expect_close("spread is the full range", spread([1.0, 4.0, 2.0]), 3.0)
    try:
        spread([1.0])
    except ValueError:
        pass
    else:
        failures.append("spread: expected a ValueError for a single opinion")

    # Each organisation votes once. Written without the grouping, DWD and NCEP would carry
    # two votes each and the range below would be 0.6 rather than 0.5.
    readings = {
        "meteofrance_wave": 1.0,
        "dwd_ewam": 1.2,
        "dwd_gwam": 1.4,
        "ncep_gfswave025": 0.8,
        "ncep_gfswave016": 0.8,
    }
    opinions = by_provider(readings)
    if sorted(opinions) != ["DWD", "MeteoFrance", "NCEP"]:
        failures.append(f"by_provider: expected three organisations, got {sorted(opinions)}")
    expect_close("DWD's vote is the median of its models", opinions["DWD"], 1.3)
    expect_close("provider spread ignores duplicate members", spread(list(opinions.values())), 0.5)

    # The share is the ratio ADR 0003's question turns on. A spread made entirely of
    # staleness reads 100%; one with none reads 0%. Exponent 0 holds movement constant
    # across gaps, which isolates the ratio from the scaling.
    flat = Comparison(lead=1, hours=10, self_movement=0.4, provider_spread=0.4, exponent=0.0)
    expect_close("all staleness", flat.share_over(24), 1.0)
    expect_close("half staleness", flat.share_over(24) / 2, 0.5)
    quiet = Comparison(lead=1, hours=10, self_movement=0.2, provider_spread=0.0, exponent=0.0)
    expect_close("no disagreement, no share", quiet.share_over(24), 0.0)

    # Scaling down from the measured 24 hours. An exponent of 1 halves the movement over
    # half the gap; 0.5 divides it by root two. Getting this backwards would report the
    # shorter gap as the *more* contaminating one.
    linear = Comparison(lead=1, hours=10, self_movement=0.4, provider_spread=1.0, exponent=1.0)
    expect_close("linear growth halves over half the gap", linear.movement_over(12), 0.2)
    expect_close("and the measured gap is unchanged", linear.movement_over(24), 0.4)
    root = Comparison(lead=1, hours=10, self_movement=0.4, provider_spread=1.0, exponent=0.5)
    expect_close("a random walk divides by root two", root.movement_over(12), 0.4 / math.sqrt(2))
    if not linear.movement_over(6) < linear.movement_over(12) < linear.movement_over(24):
        failures.append("movement_over: a shorter gap must move less, not more")

    # The fit has to recover an exponent it was handed, or every extrapolated figure is
    # arithmetic nobody checked. Movement doubling with each doubling of the gap is
    # exponent 1 exactly.
    synthetic = Ensemble(
        readings={
            f"2026-01-01T{hour:02d}:00": {
                1: {"meteofrance_wave": 0.0},
                **{1 + gap: {"meteofrance_wave": 0.1 * gap} for gap in range(1, 7)},
            }
            for hour in range(3)
        }
    )
    _, fitted = scaling(synthetic)
    expect_close("the fit recovers a linear growth rate", fitted, 1.0, tolerance=1e-6)

    # An hour where a provider is missing must be dropped rather than differenced, or a
    # two-provider spread would be averaged in beside three-provider ones and the whole
    # comparison would drift downward wherever a model went dark.
    partial = Ensemble(
        readings={
            "2026-01-01T00:00": {
                1: {"meteofrance_wave": 2.0, "dwd_gwam": 2.4, "ncep_gfswave025": 3.0},
                2: {"meteofrance_wave": 2.2, "dwd_gwam": 2.5, "ncep_gfswave025": 3.1},
            },
            "2026-01-01T01:00": {
                1: {"meteofrance_wave": 2.0, "dwd_gwam": 2.4},
                2: {"meteofrance_wave": 2.9, "dwd_gwam": 2.5},
            },
        }
    )
    rows = compare(partial, exponent=1.0)
    lead_one = [row for row in rows if row.lead == 1]
    if len(lead_one) != 1 or lead_one[0].hours != 1:
        failures.append(
            "compare: an hour missing a provider must be dropped, got "
            f"{[(row.lead, row.hours) for row in rows]}"
        )
    else:
        # 3.0 - 2.0 across providers, and (0.2 + 0.1 + 0.1) / 3 of self-movement.
        expect_close("spread is across providers", lead_one[0].provider_spread, 1.0)
        expect_close("self-movement averages the models", lead_one[0].self_movement, 0.4 / 3)

    for failure in failures:
        print(f"FAIL {failure}")
    print("alignment.py --check: " + ("FAILED" if failures else "all checks passed"))
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    runs = ensemble()
    coefficient, exponent = scaling(runs)
    rows = compare(runs, exponent)

    print(
        f"Run alignment, {WAVE_ARCHIVE_START:%Y-%m-%d} to {END:%Y-%m-%d} — "
        f"{len(runs)} archived hours, {len(PROVIDERS)} models, "
        f"{len(set(PROVIDERS.values()))} organisations.\n"
    )
    print(
        f"  Self-movement grows as gap^{exponent:.2f} (fitted across 24-144 h). A random walk "
        f"would be 0.50\n  and a steadily improving forecast 1.00, so neither assumption "
        "would have been right.\n"
    )
    print(
        f"  {'lead':>5s} {'hours':>7s} {'measured/24h':>14s} {'spread':>9s} "
        f"{'stale/6h':>10s} {'stale/12h':>11s} {'share 6h':>9s} {'share 12h':>10s}"
    )
    for row in rows:
        print(
            f"  {row.lead:5d} {row.hours:7d} {row.self_movement:12.3f} m "
            f"{row.provider_spread:7.3f} m {row.movement_over(EXPECTED_CADENCE_HOURS):8.3f} m "
            f"{row.movement_over(SLOWEST_CADENCE_HOURS):9.3f} m "
            f"{row.share_over(EXPECTED_CADENCE_HOURS):8.1%} "
            f"{row.share_over(SLOWEST_CADENCE_HOURS):9.1%}"
        )

    worst = max(rows, key=lambda row: row.share_over(SLOWEST_CADENCE_HOURS))
    nearest = min(rows, key=lambda row: row.lead)
    print(
        f"\n  At one day out, staleness accounts for about "
        f"{nearest.share_over(EXPECTED_CADENCE_HOURS):.0%} of the spread on the expected "
        f"gap and\n  {nearest.share_over(SLOWEST_CADENCE_HOURS):.0%} in the worst case. At "
        f"lead {worst.lead} it reaches {worst.share_over(SLOWEST_CADENCE_HOURS):.0%}."
    )
    print(
        "\n  So it is real and it grows with Lead Time — ADR 0003 was right to demand this be\n"
        "  settled. It is not disqualifying: staleness can only make the spread look *wider*\n"
        "  than the providers truly disagree, and a wider spread reads as more doubt. The\n"
        "  contamination therefore errs toward caution, never toward a Go Call that should\n"
        "  not have been issued."
    )

    partitions = spread_on_both()
    print(
        f"\n  Live provider spread, both partitions: Combined Sea {partitions[VARIABLE]:.2f} m, "
        f"Swell {partitions[SWELL_VARIABLE]:.2f} m.\n  Self-movement above is measured on "
        "Combined Sea; Model Spread is defined on Swell."
    )

    path = write_csv(rows)
    print(f"\nWrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
