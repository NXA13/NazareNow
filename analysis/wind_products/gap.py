"""Does the light-wind exemption survive crossing a product boundary? (#51)

The three wave bars are fitted in Hindcast units and translated into the units a Pipeline
Run reads before they ship. The light-wind exemption is not translated, and five places in
the record justify that with one claim:

    wind reaches the fit and the Pipeline Run alike from ERA5

**The first half is true and the second half is false.** `hindcast.wind()` reads ERA5 from
the archive endpoint, so the fit is ERA5. But a Pipeline Run reads wind from
`open_meteo.WEATHER_URL` — `api.open-meteo.com/v1/forecast` — which is a forecast product,
not the archive. So the exemption crosses exactly the product boundary the wave bars are
translated across, and it crosses it untranslated on a premise that does not hold. ADR 0011
records the contradiction; this module measures what it costs.

**Why it is worth measuring rather than shrugging at.** The exemption is the lowest speed
admitting the six Gold Days in the fitting split that no hour passes on direction and speed
alone. The calmest hour of the windiest of those six sits at 16.3 km/h and the fitted
exemption is 16.5 — a **0.2 km/h** margin, and the bar is rounded *up* to a 0.5 km/h step
precisely because rounding it down would drop that day out of the fit. A product gap of even
a few tenths sits inside that margin. The exemption is also *fitted* where the height bar and
both arcs were merely *verified*, and fitted numbers carry their units with them.

**The trap this module exists to avoid, and nearly fell into.**

`previous-runs-api.open-meteo.com` answers for dates long before its forecast archive opened,
and for those dates it returns **ERA5 verbatim** — the same series `hindcast.wind()` reads.
Fitted across such a span, the translation would be the reanalysis regressed against itself:
slope 1.0000, intercept 0.0000, residual 0.000, and the confident conclusion that there is no
product gap at all. That is this project's characteristic failure exactly — a response that
looks like agreement and is not.

`--probe` establishes where the backfill stops, by exact-match count rather than by
documentation. Before `BACKFILL_ENDS_AT` every hour matches ERA5 to 1e-9; after it, matches
occur at roughly the rate coincidence predicts. The measurement below starts the day after.

**What is measured.** The gap between the two products in 10 m wind speed at the Proxy
Target, at the shortest Lead Time the archive carries, over three Big-Wave Seasons. Reported
as slope, intercept and residual in the shape `analysis/overlap/measure.py` reports the wave
quantities, on all hours and separately on the band where the exemption actually decides
anything. An all-hours average is dominated by wind speeds that never block a Gold Day and
would be the wrong number to reason from.

**Shortest Lead Time, deliberately.** The base `wind_speed_10m` variable is the archive's
settled best match for a past hour, not a forecast issued days earlier. Reading
`_previous_dayN` instead would fold in the drift #14 already measured and answer a different
question: this module is about the boundary between two *products*, not about the Lead Time
axis. `analysis/forecast_error/README.md` draws the same line from the other side.

Run:
    .venv/Scripts/python.exe analysis/wind_products/gap.py
    .venv/Scripts/python.exe analysis/wind_products/gap.py --probe   # where backfill stops
    .venv/Scripts/python.exe analysis/wind_products/gap.py --check   # arithmetic, offline
"""

from __future__ import annotations

import csv
import json
import math
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
sys.path.insert(0, str(ROOT / "analysis" / "backtest"))
sys.path.insert(0, str(ROOT / "analysis" / "overlap"))

import hindcast  # noqa: E402
import measure  # noqa: E402
from nazarenow.sources.open_meteo import LATITUDE, LONGITUDE, TIMEZONE  # noqa: E402
from nazarenow.thresholds import load  # noqa: E402

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
"""The forecast product, for past dates.

`WEATHER_URL` serves the current run only and has nothing to say about last November, so
this is the one endpoint standing in for the live wind feed. Its base `wind_speed_10m` is
the settled best match — the shortest Lead Time the archive offers, which is what isolates
the product boundary from the Lead Time axis."""

CACHE = ROOT / "data" / "raw" / "wind_products"
"""Gitignored under `data/raw/`, per the repo's rule that raw archives are reproducible and
not committed. Only the derived table is."""

BACKFILL_ENDS_AT = "2022-11-16T09:00"
"""The first hour the forecast archive answers with its own data rather than with ERA5.

Established by `--probe`, not read off documentation. Every hour from 2021-01 to this one
matches `hindcast.wind()` exactly; from here on, exact matches run at about 1.4% — the rate
two independent series agree by coincidence when readings are rounded to one decimal.

November 2022 is the month it happens in: 372 of its 720 hours match exactly, which is the
signature of a boundary inside the month rather than of a patchy backfill."""

START = date(2022, 11, 17)
"""The first whole day after the backfill boundary. Whole days, so no partly-backfilled day
enters the fit."""

END = date(2025, 12, 31)
"""Where `hindcast.wind()` stops. ERA5 is the binding side here — the forecast archive runs
to the present, the Hindcast cache does not."""

EXEMPTION_BAND_KMH = 20.0
"""The band the exemption decides in.

The fitted exemption is 16.5 km/h and the general wind cap is 35. Between them, only hours
below roughly 20 km/h can turn on the exemption at all; above that the day fails on speed
regardless of which product measured it. A fit over all hours is dominated by weather that
never blocks a Gold Day and would report a slope belonging to a different question."""

FITTED_EXEMPTION_KMH = 16.5
LIGHT_WIND_STEP_KMH = 0.5
"""The exemption as `calibrate.fit_light_wind_exemption` chooses it, in ERA5 units, and the
step it is raised to.

Restated here rather than imported, because `calibrate.py` imports *this* module to
translate that very bar and importing it back would be a cycle. Restating a number is how
two files drift apart, so `main` refuses to report anything unless translating this value
reproduces the bar the system actually ships — a refit that moves the exemption fails loudly
here instead of quietly scoring the wrong bar.
"""

ATTEMPTS = 5
"""Retries per request. This module walks thirty-eight months in sequence and Open-Meteo
closes connections under rapid sequential use — the same behaviour `download_runs.py` and
`alignment.py` both retry through. Observed here on the third consecutive call."""

PAUSE_SECONDS = 1.0
"""Between requests. Politeness toward a free provider the whole project depends on."""

VARIABLE = "wind_speed_10m"
EXPECTED_UNIT = "km/h"
"""Checked on arrival, for the reason `open_meteo.py` learned the hard way: a threshold
named in km/h compared against a bare float from a response in m/s is a decision made
confidently on nonsense. Both endpoints are asked for km/h explicitly."""


def _get(params: dict[str, Any], cache_key: str) -> dict[str, Any]:
    """Fetch, or return the cached copy. Raw response kept exactly as it arrived."""
    path = CACHE / f"{cache_key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    CACHE.mkdir(parents=True, exist_ok=True)
    query = f"{PREVIOUS_RUNS_URL}?{urllib.parse.urlencode(params)}"

    body: dict[str, Any] | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(query, timeout=300) as response:
                body = json.load(response)
            break
        except urllib.error.HTTPError as error:
            # A 4xx will not become a 2xx by asking again; only 429 and 5xx are worth
            # waiting out. Retrying a malformed request would just hide it.
            if error.code not in (429, 500, 502, 503, 504) or attempt == ATTEMPTS:
                raise RuntimeError(f"{cache_key}: Open-Meteo returned {error.code}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == ATTEMPTS:
                raise RuntimeError(
                    f"{cache_key}: could not reach Open-Meteo after {ATTEMPTS} attempts: {error}"
                ) from error
        time.sleep(PAUSE_SECONDS * 2**attempt)

    if body is None:  # pragma: no cover - the loop either breaks or raises
        raise RuntimeError(f"{cache_key}: no response")
    if "error" in body:
        raise RuntimeError(f"{cache_key}: Open-Meteo refused: {body.get('reason')}")

    path.write_text(json.dumps(body), encoding="utf-8")
    return body


def _months(start: date, end: date) -> list[tuple[date, date]]:
    """Split the span into calendar months.

    Chunked so a failed retrieval costs one month rather than three years, and so the cache
    is resumable. Month boundaries rather than fixed windows because the cache key then
    reads as a date a human can find.
    """
    spans = []
    cursor = start
    while cursor <= end:
        next_month = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        spans.append((cursor, min(next_month - timedelta(days=1), end)))
        cursor = next_month
    return spans


def _read_hours(body: dict[str, Any], label: str) -> dict[str, float]:
    """Validate one response and key it by hour, dropping nulls rather than carrying them."""
    if body.get("timezone") != TIMEZONE:
        raise ValueError(
            f"{label}: Open-Meteo returned timestamps on {body.get('timezone')!r}; the "
            f"exemption is applied to Nazaré local hours on {TIMEZONE!r} (ADR 0008)"
        )
    hourly = body.get("hourly") or {}
    if VARIABLE not in hourly:
        raise ValueError(f"{label}: response is missing {VARIABLE}")
    unit = (body.get("hourly_units") or {}).get(VARIABLE)
    if unit != EXPECTED_UNIT:
        raise ValueError(
            f"{label}: {VARIABLE} arrived in {unit!r}; the exemption is named in "
            f"{EXPECTED_UNIT!r} and comparing the two would be nonsense"
        )
    return {
        at: value
        for at, value in zip(hourly["time"], hourly[VARIABLE], strict=True)
        if value is not None
    }


def forecast_wind(start: date = START, end: date = END) -> dict[str, float]:
    """The forecast product's settled wind, hour by hour, over the span."""
    readings: dict[str, float] = {}
    for index, (first, last) in enumerate(_months(start, end)):
        key = f"forecast_wind_{first:%Y-%m}"
        cached = (CACHE / f"{key}.json").exists()
        body = _get(
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": first.isoformat(),
                "end_date": last.isoformat(),
                "hourly": VARIABLE,
                "timezone": TIMEZONE,
                "wind_speed_unit": "kmh",
            },
            key,
        )
        readings.update(_read_hours(body, key))
        if not cached and index:
            time.sleep(PAUSE_SECONDS)
    if not readings:
        raise RuntimeError("the forecast archive returned no wind at all over the span")
    return readings


def hindcast_wind() -> dict[str, float]:
    """ERA5 wind, the series the exemption was fitted against."""
    series = hindcast.wind()
    return {at: hour["wind_speed_10m"] for at, hour in series.readings.items()}


@dataclass(frozen=True)
class Paired:
    """One hour both products describe."""

    at: str
    hindcast_kmh: float
    forecast_kmh: float

    @property
    def difference(self) -> float:
        """Forecast minus Hindcast. Positive means the live feed reads windier."""
        return self.forecast_kmh - self.hindcast_kmh


def pair_hours(start: date = START, end: date = END) -> list[Paired]:
    """Every hour in the span that both products report, oldest first."""
    forecast = forecast_wind(start, end)
    era5 = hindcast_wind()
    paired = [
        Paired(at=at, hindcast_kmh=era5[at], forecast_kmh=speed)
        for at, speed in forecast.items()
        if at in era5
    ]
    if not paired:
        raise RuntimeError(
            "no hour is described by both products; the Hindcast cache and the forecast "
            "archive do not overlap, and nothing here can be measured"
        )
    paired.sort(key=lambda hour: hour.at)
    _refuse_backfill(paired)
    return paired


IDENTICAL_TOLERANCE = 1e-9
BACKFILL_SHARE = 0.5
"""Above this share of exactly-matching hours, the span is ERA5 compared against itself.

Coincidental agreement runs at about 1.4% on readings rounded to one decimal, so half is
far above anything two independent products produce and far below the 100% backfill shows.
"""


def _refuse_backfill(paired: list[Paired]) -> None:
    """Fail rather than fit a translation against the reanalysis wearing a forecast's name.

    The whole finding of this module is that the archive answers for dates it has no
    forecast for. A future re-run over a wider span, or against a provider that extends its
    backfill, would otherwise silently report slope 1.0 and no gap — the confident,
    plausible, wrong answer #2 taught this project to expect.
    """
    identical = sum(1 for hour in paired if abs(hour.difference) < IDENTICAL_TOLERANCE)
    if identical > BACKFILL_SHARE * len(paired):
        raise RuntimeError(
            f"{identical} of {len(paired)} hours are identical to ERA5 to within "
            f"{IDENTICAL_TOLERANCE}: this span is the Hindcast compared against itself, not "
            f"two products. The forecast archive backfills before {BACKFILL_ENDS_AT} — see "
            "`--probe`"
        )


@dataclass(frozen=True)
class Gap:
    """The measured distance between the two products over one subset of hours."""

    subset: str
    n: int
    mean_hindcast: float
    mean_forecast: float
    bias: float
    mae: float
    rmse: float
    translation: measure.Translation

    def row(self, bar: float) -> list[str]:
        return [
            self.subset,
            str(self.n),
            f"{self.mean_hindcast:.4f}",
            f"{self.mean_forecast:.4f}",
            f"{self.bias:.4f}",
            f"{self.mae:.4f}",
            f"{self.rmse:.4f}",
            f"{self.translation.slope:.4f}",
            f"{self.translation.intercept:.4f}",
            f"{self.translation.residual_rmse:.4f}",
            f"{self.translation.apply(bar):.4f}",
        ]


def measure_gap(subset: str, hours: list[Paired], regime: str = "hours") -> Gap:
    """Fit the Hindcast-to-forecast line over `hours`, and score the raw difference too.

    The line is what a translation would be built from; the raw difference is what a reader
    needs to judge whether one is warranted. Reported together because they answer different
    halves of the question — a large scatter with no slope means the exemption is noisy but
    correctly centred, and a slope means it is in the wrong units.
    """
    if len(hours) < 2:
        raise ValueError(f"{subset}: a gap needs at least two hours to fit")
    xs = [hour.hindcast_kmh for hour in hours]
    ys = [hour.forecast_kmh for hour in hours]
    differences = [hour.difference for hour in hours]
    slope, intercept, residual = measure.least_squares(xs, ys)
    n = len(hours)
    return Gap(
        subset=subset,
        n=n,
        mean_hindcast=sum(xs) / n,
        mean_forecast=sum(ys) / n,
        bias=sum(differences) / n,
        mae=sum(abs(d) for d in differences) / n,
        rmse=(sum(d * d for d in differences) / n) ** 0.5,
        translation=measure.Translation(
            variable="light_wind_exemption_kmh",
            slope=slope,
            intercept=intercept,
            n=n,
            residual_rmse=residual,
            source="ERA5",
            regime=regime,
        ),
    )


def exemption_band(paired: list[Paired]) -> list[Paired]:
    """The hours below `EXEMPTION_BAND_KMH`, on the Hindcast axis.

    One definition, because the transform is fitted on this band and the report scores it,
    and a fit quietly cut differently from the row describing it is the kind of drift the
    numbers here would not reveal.
    """
    return [hour for hour in paired if hour.hindcast_kmh < EXEMPTION_BAND_KMH]


def fit_translation(paired: list[Paired] | None = None) -> measure.Translation:
    """The Hindcast-to-forecast transform for wind, in the regime the exemption decides in.

    What `calibrate.py` restates the fitted exemption with, in the same shape and the same
    direction as the wave transforms `measure.fit_translations` returns: `apply()` takes a
    bar fitted in Hindcast units to the units a Pipeline Run reads.

    Fitted on the exemption band rather than on all hours, by the argument
    `measure.fit_translations` uses for the big-swell subset — a transform applied to a
    threshold should be fitted in the regime that threshold operates in, and the all-hours
    slope is set by weather that never blocks a Gold Day.

    **The choice of band is not load-bearing.** The band below `EXEMPTION_BAND_KMH` and the
    narrow window straddling the bar disagree about the slope and agree about the shipped
    number once it is rounded to the calibration's step. `README.md` reports all three.

    `paired` is taken as an argument so a caller that has already paired the record does not
    pair it twice. `calibrate.py` and `backtest.py` call this once each and pass nothing,
    which is why it still knows how to do the work itself.
    """
    band = exemption_band(pair_hours() if paired is None else paired)
    if len(band) < 2:
        raise RuntimeError(
            f"fewer than two hours below {EXEMPTION_BAND_KMH:g} km/h; the regime the "
            "exemption operates in is not represented and the transform would be fitted on "
            "weather that never blocks a Gold Day"
        )
    return measure_gap(
        f"exemption band (Hindcast < {EXEMPTION_BAND_KMH:g} km/h)",
        band,
        regime=f"hours below {EXEMPTION_BAND_KMH:g} km/h",
    ).translation


@dataclass(frozen=True)
class Verdicts:
    """How often a shipped bar reproduces, on real weather, the verdict the fit intended.

    The fit decided that an hour is light-wind when its **ERA5** speed is at or below the
    fitted bar. The deployed system decides it on a **forecast** reading against whatever
    bar ships. Where those two disagree, the running system admits or refuses an hour on a
    basis no Gold Day ever justified.

    This is the only part of the cost that is measurable without #28's accumulated record.
    It is not a count of changed Watches or Go Calls: an hour must also clear height, period
    and the swell arc before the wind condition decides anything. It is the size of the
    input error the wind condition was working from.
    """

    bar: float
    n: int
    over_admitted: int
    under_admitted: int

    @property
    def disagreements(self) -> int:
        return self.over_admitted + self.under_admitted

    @property
    def share(self) -> float:
        return self.disagreements / self.n if self.n else 0.0


def exemption_verdicts(paired: list[Paired], fitted_bar: float, shipped_bar: float) -> Verdicts:
    """Score a shipped bar against the fit's intent, hour by hour.

    `over_admitted` are hours the deployed bar treats as light wind that the fit would not
    have — the direction an untranslated bar errs in here, because the forecast product
    reads lighter than ERA5. Those are hours a Watch or Go Call could be issued on wind the
    record never sanctioned. `under_admitted` is the opposite and costs recall.
    """
    over = sum(
        1 for hour in paired if hour.forecast_kmh <= shipped_bar and hour.hindcast_kmh > fitted_bar
    )
    under = sum(
        1 for hour in paired if hour.forecast_kmh > shipped_bar and hour.hindcast_kmh <= fitted_bar
    )
    return Verdicts(
        bar=shipped_bar,
        n=len(paired),
        over_admitted=over,
        under_admitted=under,
    )


def subsets(paired: list[Paired], bar: float) -> list[tuple[str, list[Paired]]]:
    """The bands the answer is read from.

    `all hours` is reported because leaving it out would look like choosing the flattering
    subset. The decision is read from the band below `EXEMPTION_BAND_KMH`, where the
    exemption is the condition that decides, and from the narrow band straddling the bar
    itself, which is where a translation would actually change a call.
    """
    return [
        ("all hours", paired),
        (
            f"exemption band (Hindcast < {EXEMPTION_BAND_KMH:g} km/h)",
            exemption_band(paired),
        ),
        (
            f"straddling the bar (Hindcast {bar - 2:g}-{bar + 2:g} km/h)",
            [h for h in paired if bar - 2 <= h.hindcast_kmh <= bar + 2],
        ),
    ]


def write_csv(gaps: list[Gap], bar: float) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "wind_product_gap.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "subset",
                "hours",
                "mean_hindcast_kmh",
                "mean_forecast_kmh",
                "bias_kmh",
                "mae_kmh",
                "rmse_kmh",
                "slope",
                "intercept",
                "residual_rmse_kmh",
                "exemption_translated_kmh",
            ]
        )
        for gap in gaps:
            writer.writerow(gap.row(bar))
    return path


PROBE_FIRST = date(2021, 1, 1)
PROBE_LAST = date(2023, 1, 31)
"""The span the probe walks, in whole months either side of the boundary.

Whole months because a partial one reports fewer hours than its neighbours and reads as a
gap in the archive rather than as the edge of the probe. Two years of backfill before the
boundary and two months of forecast after it is enough to show which side each month is on
without re-downloading the record.
"""


def probe_backfill(
    first: date = PROBE_FIRST, last: date = PROBE_LAST
) -> list[tuple[str, int, int, float]]:
    """Where does the backfill stop? Month by month, by exact-match count.

    Returns `(month, hours, exact matches, mean absolute difference)`. A backfilled month
    matches ERA5 on every hour; a real forecast month matches only by coincidence. Kept as
    a runnable probe rather than a sentence in the README because a provider can extend a
    backfill, and the day it does, the measurement above has to fail loudly.
    """
    era5 = hindcast_wind()
    rows = []
    for index, (start, end) in enumerate(_months(first, last)):
        key = f"probe_wind_{start:%Y-%m}"
        cached = (CACHE / f"{key}.json").exists()
        body = _get(
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": VARIABLE,
                "timezone": TIMEZONE,
                "wind_speed_unit": "kmh",
            },
            key,
        )
        hours = _read_hours(body, key)
        pairs = [(era5[at], speed) for at, speed in hours.items() if at in era5]
        if not pairs:
            continue
        exact = sum(1 for a, b in pairs if abs(a - b) < IDENTICAL_TOLERANCE)
        mad = sum(abs(a - b) for a, b in pairs) / len(pairs)
        rows.append((f"{start:%Y-%m}", len(pairs), exact, mad))
        if not cached and index:
            time.sleep(PAUSE_SECONDS)
    return rows


SETTLED_SHARE = 0.95
"""How one-sided a month must be before it is called one thing or the other.

The month the archive opens in is neither: it is half reanalysis and half forecast, and
reporting it as "backfill" because 51.7% of its hours match would describe a boundary as a
state. The probe exists to *find* that month, so it has to be able to name it.
"""


def _verdict(exact: int, hours: int) -> str:
    if exact >= SETTLED_SHARE * hours:
        return "BACKFILL (ERA5)"
    if exact <= (1 - SETTLED_SHARE) * hours:
        return "forecast"
    return "BOUNDARY (part of each)"


def check() -> int:
    """Self-test the arithmetic, without the network or the cache."""
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    def paired(values: list[tuple[float, float]]) -> list[Paired]:
        return [
            Paired(at=f"2023-01-01T{i:02d}:00", hindcast_kmh=a, forecast_kmh=b)
            for i, (a, b) in enumerate(values)
        ]

    # A forecast that reads uniformly windier is bias, not scatter, and a translation must
    # carry it in the intercept rather than in the slope.
    offset = measure_gap("offset", paired([(10.0, 11.0), (20.0, 21.0), (30.0, 31.0)]))
    expect("a uniform offset reads as bias", round(offset.bias, 9), 1.0)
    expect("...and as MAE", round(offset.mae, 9), 1.0)
    expect("...with slope 1", round(offset.translation.slope, 9), 1.0)
    expect("...and the offset in the intercept", round(offset.translation.intercept, 9), 1.0)
    expect("...leaving no residual", round(offset.translation.residual_rmse, 9), 0.0)

    # Scatter with no systematic component: the exemption would be noisy but correctly
    # centred, which is a different answer from being in the wrong units.
    noisy = measure_gap("noisy", paired([(10.0, 11.0), (20.0, 19.0), (30.0, 31.0), (40.0, 39.0)]))
    expect("symmetric scatter has no bias", round(noisy.bias, 9), 0.0)
    expect("...but does have MAE", round(noisy.mae, 9), 1.0)

    # The regression must run Hindcast -> forecast, because `apply()` is used to restate a
    # bar fitted in Hindcast units into the units a Pipeline Run reads. Written the other
    # way round the slope would be 1/2 instead of 2 and the shipped bar would be wrong in a
    # direction nobody would notice.
    doubled = measure_gap("doubled", paired([(1.0, 2.0), (2.0, 4.0), (3.0, 6.0)]))
    expect("the line maps Hindcast to forecast", round(doubled.translation.slope, 9), 2.0)
    expect("...and applies in that direction", round(doubled.translation.apply(10.0), 9), 20.0)
    expect("...and inverts back", round(doubled.translation.invert(20.0), 9), 10.0)

    # The backfill guard is the finding, so it is tested rather than trusted. A span that is
    # mostly ERA5 compared against itself must fail loudly, not report slope 1.0.
    identical = paired([(5.0, 5.0), (6.0, 6.0), (7.0, 7.0), (8.0, 9.0)])
    try:
        _refuse_backfill(identical)
        failures.append("backfill guard: a span of identical hours was accepted")
    except RuntimeError as error:
        expect("the guard names the boundary", BACKFILL_ENDS_AT in str(error), True)

    # ...and a genuine span must pass it. Coincidental agreement is normal at one decimal.
    try:
        _refuse_backfill(paired([(5.0, 5.0), (6.0, 7.0), (7.0, 6.0), (8.0, 9.0)]))
    except RuntimeError as error:
        failures.append(f"backfill guard: a genuine span was refused ({error})")

    # Whole calendar months, and the last one clipped to the end of the span rather than
    # running past it — a month of hours that do not exist would be fetched as nulls and
    # quietly shrink the fit.
    spans = _months(date(2022, 11, 17), date(2023, 1, 10))
    expect(
        "months are chunked and clipped",
        spans,
        [
            (date(2022, 11, 17), date(2022, 11, 30)),
            (date(2022, 12, 1), date(2022, 12, 31)),
            (date(2023, 1, 1), date(2023, 1, 10)),
        ],
    )

    # The verdict counts are the headline of this whole measurement, and the two directions
    # are trivially transposable — a swapped comparison would still produce two plausible
    # numbers that sum to the same total, and the conclusion would reverse in silence. So
    # each direction is pinned separately, on hours built to exercise exactly one of them.
    #
    # Fit admits ERA5 <= 16.5; the deployed bar is applied to the forecast reading.
    fit_admits_only = Paired(at="h", hindcast_kmh=16.0, forecast_kmh=20.0)
    bar_admits_only = Paired(at="h", hindcast_kmh=18.0, forecast_kmh=12.0)
    both_admit = Paired(at="h", hindcast_kmh=10.0, forecast_kmh=9.0)
    neither = Paired(at="h", hindcast_kmh=30.0, forecast_kmh=28.0)

    over = exemption_verdicts([bar_admits_only], 16.5, 16.5)
    expect("a bar admitting what the fit refuses is over-admission", over.over_admitted, 1)
    expect("...and not under-admission", over.under_admitted, 0)

    under = exemption_verdicts([fit_admits_only], 16.5, 16.5)
    expect("a bar refusing what the fit admits is under-admission", under.under_admitted, 1)
    expect("...and not over-admission", under.over_admitted, 0)

    agreed = exemption_verdicts([both_admit, neither], 16.5, 16.5)
    expect("hours the two agree on count as neither", agreed.disagreements, 0)

    # The boundary is `<=` on both sides: an hour exactly at the bar is admitted, not refused.
    # Written as `<` the Gold Day that set the exemption falls straight back out of it.
    at_both_bars = Paired(at="h", hindcast_kmh=16.5, forecast_kmh=14.5)
    expect(
        "an hour exactly at both bars disagrees with nothing",
        exemption_verdicts([at_both_bars], 16.5, 14.5).disagreements,
        0,
    )

    mixed = exemption_verdicts([bar_admits_only, fit_admits_only, both_admit], 16.5, 16.5)
    expect("the share counts every hour, not just the disagreeing ones", mixed.n, 3)
    expect("...and reports two of three", round(mixed.share, 6), round(2 / 3, 6))

    # The month the archive opens in is the one the probe exists to find, so it must not be
    # rounded into either neighbour. 372 of 720 is the real reading from 2022-11.
    expect("a fully backfilled month is named", _verdict(744, 744), "BACKFILL (ERA5)")
    expect("a forecast month is named", _verdict(3, 744), "forecast")
    expect("the boundary month is neither", _verdict(372, 720), "BOUNDARY (part of each)")

    # A response in m/s must fail rather than be compared against a bar named in km/h.
    try:
        _read_hours(
            {
                "timezone": TIMEZONE,
                "hourly": {"time": ["2023-01-01T00:00"], VARIABLE: [4.0]},
                "hourly_units": {VARIABLE: "m/s"},
            },
            "units",
        )
        failures.append("units: a response in m/s was accepted")
    except ValueError:
        pass

    # A null hour is absent, never a zero. Zero km/h is a calm hour that passes the
    # exemption, and letting a missing reading become one would invent light-wind hours.
    kept = _read_hours(
        {
            "timezone": TIMEZONE,
            "hourly": {"time": ["2023-01-01T00:00", "2023-01-01T01:00"], VARIABLE: [None, 3.0]},
            "hourly_units": {VARIABLE: EXPECTED_UNIT},
        },
        "nulls",
    )
    expect("a null hour is dropped, not zeroed", kept, {"2023-01-01T01:00": 3.0})

    print("gap.py --check:", "FAILED" if failures else "ok")
    for failure in failures:
        print("  -", failure)
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    if "--probe" in sys.argv:
        print(f"Backfill probe: exact matches against ERA5, {LATITUDE},{LONGITUDE}\n")
        print(f"{'month':>8}  {'hours':>5}  {'exact':>5}  {'mean|diff|':>10}  verdict")
        for month, hours, exact, mad in probe_backfill():
            print(f"{month:>8}  {hours:5d}  {exact:5d}  {mad:10.3f}  {_verdict(exact, hours)}")
        print(f"\nBackfill ends at {BACKFILL_ENDS_AT}; the measurement starts {START}.")
        return 0

    # Read from the shipped file rather than retyped, so this measurement cannot end up
    # describing a bar the system no longer applies.
    shipped_bar = load().light_wind_exemption_kmh

    # Every subset below is cut on the *Hindcast* axis and every "translates to" restates a
    # bar the fit chose, so both take the fitted value. Reading the shipped bar here instead
    # would straddle the wrong window and translate an already-translated number — which is
    # what this file did until the calibration first shipped a translated exemption.
    paired = pair_hours()
    gaps = [
        measure_gap(name, hours)
        for name, hours in subsets(paired, FITTED_EXEMPTION_KMH)
        if len(hours) >= 2
    ]

    print(f"Wind across the product boundary at {LATITUDE},{LONGITUDE}")
    print(f"{START} to {END}, {len(paired)} hours both products describe\n")
    for gap in gaps:
        print(f"{gap.subset}  (n={gap.n})")
        print(
            f"  forecast - Hindcast: bias {gap.bias:+.3f} km/h, "
            f"MAE {gap.mae:.3f}, RMSE {gap.rmse:.3f}"
        )
        print(
            f"  forecast = {gap.translation.slope:.4f} x Hindcast "
            f"{gap.translation.intercept:+.4f}, residual RMSE "
            f"{gap.translation.residual_rmse:.3f}"
        )
        print(
            f"  the {FITTED_EXEMPTION_KMH:g} km/h fitted exemption translates to "
            f"{gap.translation.apply(FITTED_EXEMPTION_KMH):.2f} km/h "
            f"({gap.translation.apply(FITTED_EXEMPTION_KMH) - FITTED_EXEMPTION_KMH:+.2f})"
        )
    # What the bar was doing before #51 translated it, against what it does now. Before #51
    # the shipped bar *was* the fitted bar, so the comparison is the fitted value against
    # its translation.
    translation = fit_translation(paired)
    translated = math.ceil(translation.apply(FITTED_EXEMPTION_KMH) / LIGHT_WIND_STEP_KMH) * (
        LIGHT_WIND_STEP_KMH
    )
    if translated != shipped_bar:
        raise RuntimeError(
            f"translating the fitted exemption ({FITTED_EXEMPTION_KMH:g} km/h) gives "
            f"{translated:g} km/h, but the system ships {shipped_bar:g}. Either the "
            "calibration has been refitted and FITTED_EXEMPTION_KMH is stale, or the shipped "
            "file was edited by hand — and #39 says a threshold moves by being rewritten by "
            "the fit"
        )
    print(
        f"\nAgainst the fit's own verdict (ERA5 <= {FITTED_EXEMPTION_KMH:g} km/h), "
        f"{len(paired)} hours:"
    )
    for label, shipped in (
        ("untranslated (before #51)", FITTED_EXEMPTION_KMH),
        ("shipped", shipped_bar),
    ):
        verdicts = exemption_verdicts(paired, FITTED_EXEMPTION_KMH, shipped)
        print(
            f"  {label:26s} bar {verdicts.bar:5.2f} km/h: "
            f"{verdicts.over_admitted:5d} admitted the fit would refuse, "
            f"{verdicts.under_admitted:5d} refused it would admit "
            f"({verdicts.share:.1%} disagree)"
        )

    path = write_csv(gaps, FITTED_EXEMPTION_KMH)
    print(f"\nwrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
