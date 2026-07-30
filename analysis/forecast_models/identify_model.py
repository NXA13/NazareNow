"""Which wave model actually serves Nazaré, and how stale is what we are given?

Two questions this project has been assuming answers to.

ADR 0005 states that "third-party wave models publish every six hours" and sets the
Pipeline Run's cadence from it. Open-Meteo's own documentation says that holds for ECMWF
WAM and GFS Wave, while MeteoFrance's wave model and DWD's EWAM/GWAM publish every twelve.
The pipeline requests no `models` parameter, so it receives Open-Meteo's `best_match`
selection — and nothing in this project establishes which model that resolves to at Praia
do Norte, or therefore how often our inputs actually change.

That matters twice over. It sets the honest polling cadence for #7, and it bears directly
on #8: ADR 0003 wants Model Spread taken as disagreement between independent models, but
models on six- and twelve-hourly cycles disagree partly because one is half a day staler
than the other. Reading that as forecast uncertainty would be measuring our own sampling
and calling it doubt.

This script asks the provider rather than assuming. It fetches the same forecast from
`best_match` and from each named model, then reports which named model `best_match` is
identical to.

Run it directly; it needs no credentials. Like the rest of `analysis/`, CI lints it but
does not run it.

    python analysis/forecast_models/identify_model.py
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# Monican02's position, the same point the Pipeline Run requests.
LATITUDE = 39.56
LONGITUDE = -9.21

# Every model Open-Meteo offers for this endpoint. Coverage notes are the provider's.
# Note the NCEP identifiers. Open-Meteo's documentation calls them `gfs_wave025` and
# `gfs_wave016`; the API rejects both with "Cannot initialize MultiDomains from invalid
# String value". The working names are below, and this script listing the documented ones
# meant it could not reproduce the table in the README beside it.
MODELS = [
    "best_match",
    "ecmwf_wam",
    "ecmwf_wam025",
    "meteofrance_wave",
    "dwd_ewam",  # Europe only
    "dwd_gwam",
    "ncep_gfswave025",
    "ncep_gfswave016",  # 52.5°N–15°S, so Nazaré at 39.56°N is inside it
]

# The variables the pipeline actually reads, so a match here means a match on the data the
# system uses rather than on some variable it ignores.
VARIABLES = ["wave_height", "swell_wave_height", "swell_wave_period", "swell_wave_direction"]


def fetch(model: str) -> dict[str, Any]:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(VARIABLES),
        "forecast_days": 3,
        "timezone": "UTC",
        "length_unit": "metric",
        "models": model,
    }
    url = f"{MARINE_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 — fixed https host
        return json.loads(response.read())


def series(body: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The hourly readings as comparable rows, ignoring any trailing nulls."""
    hourly = body.get("hourly", {})
    if not hourly:
        return []
    rows = list(zip(*(hourly.get(name, []) for name in VARIABLES), strict=False))
    return [row for row in rows if any(value is not None for value in row)]


def missing_variables(body: dict[str, Any]) -> list[str]:
    """Variables a model returns nothing for, though it answered 200.

    ECMWF WAM carries combined wave height at Nazaré and no swell partition, so it cannot
    take part in the Model Spread of #8 on the variables this project reads. Judging a
    model by its status code alone would record it as agreeing when it had said nothing:
    `gfs_seamless`, `gfs_global` and `meteofrance_seamless` all answer 200 here with every
    value null.
    """
    hourly = body.get("hourly", {})
    return [name for name in VARIABLES if all(value is None for value in hourly.get(name, [None]))]


def main() -> int:
    results: dict[str, list[tuple[Any, ...]]] = {}
    for model in MODELS:
        try:
            body = fetch(model)
        except Exception as error:  # noqa: BLE001 — a model with no coverage here is a result
            print(f"{model:<20} no data ({type(error).__name__}: {error})")
            continue
        rows = series(body)
        results[model] = rows
        first = rows[0] if rows else None
        absent = missing_variables(body)
        note = f"   no data for: {', '.join(absent)}" if absent else ""
        print(f"{model:<20} {len(rows):>4} usable hours   first hour: {first}{note}")

    reference = results.get("best_match")
    if not reference:
        print("\nbest_match returned nothing; cannot identify the active model.")
        return 1

    print(f"\nbest_match at {LATITUDE}, {LONGITUDE} is identical to:")
    identical = [
        model
        for model, rows in results.items()
        if model != "best_match" and rows[: len(reference)] == reference
    ]
    for model in identical or ["(no named model matched exactly)"]:
        print(f"  {model}")

    if not identical:
        print("\nClosest by first hour:")
        for model, rows in results.items():
            if model == "best_match" or not rows:
                continue
            print(f"  {model:<20} {rows[0]}  vs best_match {reference[0]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
