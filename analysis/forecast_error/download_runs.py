"""Caching the archived forecast runs #14 measures the Forecast Error Profile from.

ADR 0004 separates Amplification from Forecast Error: the Amplification Model learns the
physical relationship from the Hindcast, and forecast unreliability is characterised
independently from Open-Meteo's Previous Runs archive, which serves what the model actually
predicted one to seven days ahead of a past date. This module retrieves that archive and
caches it, so deriving the profile does not re-download nine months of ocean.

**Two hosts, because the archive is two archives.**

Waves come from the marine endpoint's `_previous_dayN` variables. Wind comes from
`previous-runs-api.open-meteo.com`, which has no marine endpoint at all — a negative result
`analysis/model_spread/README.md` already records. The two archives do not begin on the same
date and one of them does not carry the Swell partition, which is why `probe_archive` exists
and why its findings are a table in the README rather than a sentence.

The coordinates, timezone and marine endpoint are imported from the running system rather
than retyped, so the profile cannot end up describing different water from the thing it will
eventually be injected into.

Run:
    .venv/Scripts/python.exe analysis/forecast_error/download_runs.py
    .venv/Scripts/python.exe analysis/forecast_error/download_runs.py --probe
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))

from nazarenow.sources.open_meteo import (  # noqa: E402
    LATITUDE,
    LONGITUDE,
    MARINE_URL,
    TIMEZONE,
)

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
"""Archived wind runs. The live pipeline's `WEATHER_URL` serves only the current run and
returns nothing for what it said last Tuesday, so this is the one endpoint #14 cannot
borrow from the running system. It has no marine counterpart — see `probe_archive`."""

CACHE = Path(__file__).resolve().parents[2] / "data" / "raw" / "forecast_runs"
"""Gitignored under `data/raw/`, per the repo's rule that raw archives are reproducible and
not committed. Only the derived profile and its tables are."""

WAVE_ARCHIVE_START = date(2025, 11, 16)
"""The first model run the marine archive retains, established by probing rather than read
off documentation.

`wave_height_previous_day1` first carries a value at 2025-11-17T15:00 and
`wave_height_previous_day7` at 2025-11-23T15:00 — six days apart, both pointing back to the
same run at 2025-11-16T15:00, which is the signature of an archive opened on that date
rather than a patchy backfill. Every hour from there to the present is populated, at every
Lead Time, with no interior gaps.

**ADR 0004 says this archive begins January 2024.** That is true of the wind archive below
and false of this one. The ADR carries an amendment recording the difference; the
consequence for #14 is that the wave side has **one** Big-Wave Season to measure, not two."""

WIND_ARCHIVE_START = date(2024, 3, 1)
"""Where the wind archive is known to carry previous runs. Probed, not documented: nothing
is returned for 2024-01-05 and everything is returned for 2024-03-01. Stated as the
conservative bound it is — the true start lies somewhere inside that gap, and #14 does not
need it pinned because the wave archive binds first."""

END = date(2026, 7, 31)
"""Fixed rather than "yesterday", so the derivation is reproducible.

Held a few days short of the present deliberately. The day-0 series this profile measures
drift against is the archived best match, and for a date close enough to now that reading
is still partly a forecast rather than the model's settled analysis — which would quietly
shrink the measured error at exactly the short Lead Times."""

LEAD_TIMES = (1, 2, 3, 4, 5, 6, 7)
"""ADR 0004's hard ceiling. Previous Runs stops at seven days, so beyond that there is no
Forecast Error Profile to measure and Watch-tier confidence rests on Model Spread alone."""

WAVE_VARIABLES = ("wave_height", "wave_period", "wave_direction")
"""The Combined Sea partition, which is all the marine archive carries at any Lead Time.

`swell_wave_height`, `swell_wave_period` and `swell_wave_direction` are **accepted** by the
endpoint with a `_previous_dayN` suffix and come back entirely null, at every date tested
across the archive's whole span. That is this project's characteristic failure — a response
that looks like agreement and is not — so `probe_archive` records it as measured rather than
leaving a reader to infer it from an empty column."""

SWELL_VARIABLES = ("swell_wave_height", "swell_wave_period", "swell_wave_direction")

WIND_VARIABLES = ("wind_speed_10m", "wind_direction_10m")

EXPECTED_UNITS = {
    "wave_height": "m",
    "wave_period": "s",
    "wave_direction": "°",
    "wind_speed_10m": "km/h",
    "wind_direction_10m": "°",
}
"""Checked on arrival, for the reason `open_meteo.py` learned the hard way: a threshold
named in metres compared against a bare float from a response in some other unit is a
decision made confidently on nonsense."""


def _previous_day_names(variables: tuple[str, ...]) -> list[str]:
    """Every variable at day 0 and at each Lead Time, in one request.

    Day 0 travels with the rest because the profile is a *difference*, and fetching the
    reference separately would let it come from a different retrieval — the same sampling
    drift `analysis/model_spread/probe.py` avoids by asking for all five models at once.
    """
    names = list(variables)
    for variable in variables:
        names.extend(f"{variable}_previous_day{lead}" for lead in LEAD_TIMES)
    return names


def _months(start: date, end: date) -> list[tuple[date, date]]:
    """Split the span into calendar months.

    Chunked so a failed retrieval costs one month rather than the whole archive, and so
    the cache is resumable. Month boundaries rather than fixed-length windows because the
    cache key then reads as a date a human can find.
    """
    spans = []
    cursor = start
    while cursor <= end:
        if cursor.month == 12:
            next_month = date(cursor.year + 1, 1, 1)
        else:
            next_month = date(cursor.year, cursor.month + 1, 1)
        spans.append((cursor, min(next_month - timedelta(days=1), end)))
        cursor = next_month
    return spans


ATTEMPTS = 4
"""Retries per request, because this module makes tens of them in a row.

`hindcast.py` fetches three times and can afford to fail on the first refusal. This one
walks nine months across two hosts and was reset mid-probe on the third consecutive call —
a public free endpoint closing a connection under rapid sequential use, not a fault in the
request. Retrying is what keeps a nine-month retrieval from being abandoned six requests in,
and the cache means a resumed run only repeats what it had not already stored."""

PAUSE_SECONDS = 1.0
"""Between requests. Open-Meteo asks nothing of us here and is free; this is politeness
toward a provider the whole project depends on, and it costs under half a minute."""


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
            # A 4xx will not become a 2xx by asking again; only 429 and 5xx are worth
            # waiting out. Retrying a malformed request would just hide it.
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


@dataclass(frozen=True)
class Runs:
    """Archived forecasts for one span, keyed by hour and Lead Time.

    `readings[hour][lead][variable]` is what the model said about `hour` when asked `lead`
    days earlier; `readings[hour][0]` is the archived best match for that hour. An hour a
    Lead Time did not answer for is **absent** rather than present-and-None, so a caller
    gets a number or a `KeyError` and never a null that arithmetic turns into nonsense.
    """

    name: str
    readings: dict[str, dict[int, dict[str, float]]]

    def __len__(self) -> int:
        return len(self.readings)

    def pairs(self, variable: str, lead: int) -> list[tuple[str, float, float]]:
        """Every hour where both the lead-`lead` forecast and the day-0 reference exist."""
        found = []
        for hour, by_lead in self.readings.items():
            forecast = by_lead.get(lead, {}).get(variable)
            reference = by_lead.get(0, {}).get(variable)
            if forecast is not None and reference is not None:
                found.append((hour, forecast, reference))
        return sorted(found)


def _parse(body: dict[str, Any], name: str, variables: tuple[str, ...]) -> Runs:
    """Validate a response and key it by hour and Lead Time.

    Suspicious of the provider in the same way `hindcast.py` is. The timezone check is not
    ceremony here: `previous_dayN` counts back from the timestamp it is attached to, so a
    response silently returned on GMT would shift every Lead Time by an hour against the
    Nazaré local days ADR 0008 requires, and nothing downstream would notice.
    """
    if body.get("timezone") != TIMEZONE:
        raise ValueError(
            f"{name}: Open-Meteo returned timestamps on {body.get('timezone')!r}; the "
            f"Lead Times below count back from Nazaré local hours on {TIMEZONE!r} "
            "(ADR 0008) and would each be measured against the wrong run"
        )

    hourly = body.get("hourly") or {}
    times = hourly.get("time")
    if not times:
        raise ValueError(f"{name}: response has no time axis")

    units = body.get("hourly_units") or {}
    wrong = {v: units.get(v) for v in variables if units.get(v) != EXPECTED_UNITS[v]}
    if wrong:
        raise ValueError(
            f"{name}: unexpected units {wrong}; this profile is measured in metres, "
            "seconds, degrees and km/h"
        )

    readings: dict[str, dict[int, dict[str, float]]] = {}
    for index, at in enumerate(times):
        by_lead: dict[int, dict[str, float]] = {}
        for lead in (0, *LEAD_TIMES):
            hour: dict[str, float] = {}
            for variable in variables:
                key = variable if lead == 0 else f"{variable}_previous_day{lead}"
                series = hourly.get(key)
                value = series[index] if series is not None else None
                if value is not None:
                    hour[variable] = value
            if hour:
                by_lead[lead] = hour
        if by_lead:
            readings[at] = by_lead

    if not readings:
        raise ValueError(
            f"{name}: every hour of {times[0]}..{times[-1]} was null for all of "
            f"{list(variables)} — this archive does not carry them here"
        )
    return Runs(name=name, readings=readings)


def _merge(parts: list[Runs], name: str) -> Runs:
    merged: dict[str, dict[int, dict[str, float]]] = {}
    for part in parts:
        merged.update(part.readings)
    return Runs(name=name, readings=merged)


def waves() -> Runs:
    """Combined Sea at every Lead Time, from the marine archive's first run to `END`."""
    parts = []
    for start, end in _months(WAVE_ARCHIVE_START, END):
        body = _get(
            MARINE_URL,
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "hourly": ",".join(_previous_day_names(WAVE_VARIABLES)),
                "timezone": TIMEZONE,
                "length_unit": "metric",
            },
            f"marine_{start:%Y-%m}",
        )
        parts.append(_parse(body, f"marine {start:%Y-%m}", WAVE_VARIABLES))
    return _merge(parts, "marine combined sea runs")


def wind(start: date | None = None) -> Runs:
    """Wind at every Lead Time.

    Defaults to the wave archive's start rather than its own, because #14 pairs the two and
    a wind hour with no wave hour beside it has nothing to be part of. `start` is exposed so
    the README can report how much deeper the wind archive runs than the waves.
    """
    parts = []
    for chunk_start, chunk_end in _months(start or WAVE_ARCHIVE_START, END):
        body = _get(
            PREVIOUS_RUNS_URL,
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": chunk_start.isoformat(),
                "end_date": chunk_end.isoformat(),
                "hourly": ",".join(_previous_day_names(WIND_VARIABLES)),
                "timezone": TIMEZONE,
                "wind_speed_unit": "kmh",
            },
            f"wind_{chunk_start:%Y-%m}",
        )
        parts.append(_parse(body, f"wind {chunk_start:%Y-%m}", WIND_VARIABLES))
    return _merge(parts, "previous-runs wind")


def probe_archive() -> list[tuple[str, str, str]]:
    """What the archive carries, recorded as measured rather than assumed.

    Every row here was a plausible assumption before it was checked, and three of them are
    load-bearing enough that #14 would have been designed wrongly around any of them:
    ADR 0004's January 2024 start, the Swell partition being archived like everything else,
    and the previous-runs host serving marine data.

    The Swell rows are the dangerous ones. The endpoint returns **200 with the variable
    present and every value null**, so code that requested it and checked the status would
    believe it had a swell forecast archive and would find out otherwise only when the
    profile came back computed on nothing.
    """
    sampled = date(2026, 1, 10)
    findings: list[tuple[str, str, str]] = []

    def count(url: str, variable: str, extra: dict[str, Any], key: str) -> int:
        body = _get(
            url,
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "start_date": sampled.isoformat(),
                "end_date": sampled.isoformat(),
                "hourly": variable,
                "timezone": TIMEZONE,
                **extra,
            },
            key,
        )
        series = (body.get("hourly") or {}).get(variable) or []
        return sum(1 for value in series if value is not None)

    for variable in WAVE_VARIABLES:
        hours = count(
            MARINE_URL,
            f"{variable}_previous_day1",
            {"length_unit": "metric"},
            f"probe_{variable}",
        )
        findings.append(
            (
                f"marine {variable}_previous_day1",
                f"{hours}/24 hours",
                "archived" if hours else "accepted, returns null",
            )
        )

    for variable in SWELL_VARIABLES:
        hours = count(
            MARINE_URL,
            f"{variable}_previous_day1",
            {"length_unit": "metric"},
            f"probe_{variable}",
        )
        findings.append(
            (
                f"marine {variable}_previous_day1",
                f"{hours}/24 hours",
                "archived" if hours else "**accepted, returns null** — not archived",
            )
        )

    for variable in WIND_VARIABLES:
        hours = count(
            PREVIOUS_RUNS_URL,
            f"{variable}_previous_day1",
            {"wind_speed_unit": "kmh"},
            f"probe_{variable}",
        )
        findings.append(
            (
                f"previous-runs {variable}_previous_day1",
                f"{hours}/24 hours",
                "archived" if hours else "accepted, returns null",
            )
        )

    return findings


def main() -> int:
    if "--probe" in sys.argv:
        print("What the archives carry, sampled on 2026-01-10:\n")
        print(f"  {'variable':48s} {'coverage':14s} verdict")
        for label, coverage, verdict in probe_archive():
            print(f"  {label:48s} {coverage:14s} {verdict}")
        return 0

    print(
        f"Caching archived runs for {WAVE_ARCHIVE_START:%Y-%m-%d}..{END:%Y-%m-%d}, "
        f"Lead Times {LEAD_TIMES[0]}-{LEAD_TIMES[-1]}."
    )
    wave_runs = waves()
    wind_runs = wind()
    print(f"  {len(wave_runs):6d} hours of Combined Sea runs")
    print(f"  {len(wind_runs):6d} hours of wind runs")
    print(f"\nCached under {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
