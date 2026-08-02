"""Fetching the Hindcast the backtest scores against.

Ticket #11 needs Offshore Conditions as they actually were, hour by hour, for as much of
the record as can be had. This module gets them from Open-Meteo, which needs no
credentials, and caches the raw responses so a re-run of the report does not re-download
sixteen years of ocean.

**Three series, because no single one covers both the range and the variables.**

`era5_ocean` reaches back to 2011 but describes the **Combined Sea** only: it returns
`wave_height`, `wave_period`, `wave_peak_period` and `wave_direction`, and returns null
for every `swell_wave_*` variable. The operational models that do carry the **Swell**
partition — the variables the live Pipeline Run actually reads — begin around 2022.

CONTEXT.md holds Combined Sea and Swell apart deliberately, and this is exactly where
conflating them would do damage: the Heuristic Baseline's period and direction thresholds
are written in Swell terms, and scoring them against Combined Sea numbers because both are
called "period" would produce a benchmark that looks rigorous and measures the wrong
variable. `swell.py` quantifies what the substitution costs; this module only keeps the
two labelled.

The coordinates, timezone and endpoints are imported from the running system rather than
retyped, so the backtest cannot end up describing different water from the thing it scores.

Run:
    .venv/Scripts/python.exe analysis/backtest/hindcast.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))

from nazarenow.sources.open_meteo import (  # noqa: E402
    LATITUDE,
    LONGITUDE,
    MARINE_URL,
    TIMEZONE,
)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
"""ERA5 wind. The live pipeline's `WEATHER_URL` serves forecasts only and returns nothing
for a date in 2011, so this is the one endpoint the backtest cannot borrow."""

CACHE = Path(__file__).resolve().parents[2] / "data" / "raw" / "hindcast"
"""Gitignored under `data/raw/`, per the repo's rule that raw archives are reproducible
and not committed. Only the derived report and its tables are."""

# The record starts in 2011 because the first Gold Day is 2011-11-01 and ERA5 offers
# nothing about Nazaré before that which this project has a use for.
START = "2011-01-01"
END = "2025-12-31"

# The Swell partition exists from here. Established by probing each marine model rather
# than read off documentation — see the report.
OPERATIONAL_START = "2022-01-01"

COMBINED_SEA = ("wave_height", "wave_period", "wave_direction")
SWELL = ("swell_wave_height", "swell_wave_period", "swell_wave_direction")
WIND = ("wind_speed_10m", "wind_direction_10m")

PEAK_PERIOD = "wave_peak_period"
"""Fetched, but optional, and deliberately not part of `COMBINED_SEA`.

ERA5 carries it only to **2024-11**; every hour from 2024-12 onward is null. Requiring it
alongside the rest silently dropped two Gold Days — 2025-02-18 and 2025-12-13 lost all 24
of their hours — which is precisely the plausible-looking wrong data this project keeps
tripping over. It is kept because `swell.py` weighs it as a candidate predictor and the
report has to show that comparison, not merely assert its conclusion."""

# Open-Meteo's declared unit for every variable read here, checked on arrival. The
# Heuristic Baseline compares bare floats against thresholds named in metres, seconds and
# km/h; `open_meteo.py` learned the hard way that carrying units for display and dropping
# them before the comparison lets a response in furlongs through.
EXPECTED_UNITS = {
    "wave_height": "m",
    "wave_period": "s",
    "wave_peak_period": "s",
    "wave_direction": "°",
    "swell_wave_height": "m",
    "swell_wave_period": "s",
    "swell_wave_direction": "°",
    "wind_speed_10m": "km/h",
    "wind_direction_10m": "°",
}


@dataclass(frozen=True)
class Series:
    """One provider response, validated and keyed by hour.

    `readings` maps a local timestamp to the variables at that hour. An hour the provider
    left null is absent rather than present-and-None: a caller asking for a variable gets
    either a number or a `KeyError`, never a null that arithmetic turns into nonsense.
    """

    name: str
    latitude: float
    longitude: float
    readings: dict[str, dict[str, float]]

    def __len__(self) -> int:
        return len(self.readings)


def _get(url: str, params: dict[str, Any], cache_key: str) -> dict[str, Any]:
    """Fetch, or return the cached copy. Raw response kept exactly as it arrived."""
    path = CACHE / f"{cache_key}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    CACHE.mkdir(parents=True, exist_ok=True)
    query = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(query, timeout=300) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{cache_key}: Open-Meteo returned {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{cache_key}: could not reach Open-Meteo: {error}") from error

    if "error" in body:
        raise RuntimeError(f"{cache_key}: Open-Meteo refused: {body.get('reason')}")

    path.write_text(json.dumps(body), encoding="utf-8")
    return body


def _parse(
    body: dict[str, Any],
    name: str,
    variables: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> Series:
    """Validate a response and key it by hour.

    An hour survives when every variable in `variables` is present; those in `optional`
    are carried when the provider has them and simply absent when it does not, so a
    variable that stops partway through the record cannot take the rest of the hour with
    it.

    Suspicious of the provider in the same way `open_meteo.py` is, and for the same
    reason: ticket #2's lesson was that this project's characteristic failure is data
    that arrives looking plausible and is wrong. A silently truncated range or a variable
    that came back entirely null would otherwise become a benchmark nobody could question.
    """
    if body.get("timezone") != TIMEZONE:
        raise ValueError(
            f"{name}: Open-Meteo returned timestamps on {body.get('timezone')!r}; this "
            f"backtest groups hours into Nazaré local days on {TIMEZONE!r} (ADR 0008) "
            "and would put them on the wrong date"
        )

    hourly = body.get("hourly") or {}
    times = hourly.get("time")
    if not times:
        raise ValueError(f"{name}: response has no time axis")

    missing = [v for v in variables if v not in hourly]
    if missing:
        raise ValueError(f"{name}: response is missing variables: {missing}")

    present = variables + tuple(v for v in optional if v in hourly)
    units = body.get("hourly_units") or {}
    wrong = {v: units.get(v) for v in present if units.get(v) != EXPECTED_UNITS[v]}
    if wrong:
        raise ValueError(
            f"{name}: unexpected units {wrong}; the thresholds this backtest scores are "
            "named in metres, seconds and km/h"
        )

    readings: dict[str, dict[str, float]] = {}
    for index, at in enumerate(times):
        hour = {v: hourly[v][index] for v in variables}
        if any(value is None for value in hour.values()):
            continue
        for name_ in optional:
            value = hourly.get(name_, [])[index] if name_ in hourly else None
            if value is not None:
                hour[name_] = value
        readings[at] = hour

    if not readings:
        raise ValueError(
            f"{name}: every hour of {times[0]}..{times[-1]} was null for at least one of "
            f"{list(variables)} — the model does not carry these variables here"
        )
    return Series(
        name=name,
        latitude=body["latitude"],
        longitude=body["longitude"],
        readings=readings,
    )


def combined_sea() -> Series:
    """ERA5 Combined Sea, 2011-2025. No Swell partition — see the module docstring."""
    body = _get(
        MARINE_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "start_date": START,
            "end_date": END,
            "hourly": ",".join(COMBINED_SEA + (PEAK_PERIOD,)),
            "models": "era5_ocean",
            "timezone": TIMEZONE,
        },
        "era5_combined_sea",
    )
    return _parse(body, "era5 combined sea", COMBINED_SEA, optional=(PEAK_PERIOD,))


def wind() -> Series:
    """ERA5 wind, 2011-2025."""
    body = _get(
        ARCHIVE_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "start_date": START,
            "end_date": END,
            "hourly": ",".join(WIND),
            "timezone": TIMEZONE,
        },
        "era5_wind",
    )
    return _parse(body, "era5 wind", WIND)


def operational_swell() -> Series:
    """The real Swell partition, 2022-2025.

    `best_match` is what the live Pipeline Run reads, so scoring against this series is
    the one part of the backtest with no variable substitution in it at all — the same
    provider, the same model, the same variable names the running system consumes.
    """
    body = _get(
        MARINE_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "start_date": OPERATIONAL_START,
            "end_date": END,
            "hourly": ",".join(COMBINED_SEA[:1] + SWELL),
            "models": "best_match",
            "timezone": TIMEZONE,
        },
        "operational_swell",
    )
    return _parse(body, "operational swell", COMBINED_SEA[:1] + SWELL)


def main() -> int:
    for series in (combined_sea(), wind(), operational_swell()):
        print(
            f"{series.name:22s} {len(series):6d} hours  "
            f"grid {series.latitude:.4f},{series.longitude:.4f}"
        )
    print(f"\nCached under {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
