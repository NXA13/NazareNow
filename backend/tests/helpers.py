"""Shared fixtures for building stubbed provider responses.

Conditions are specified per date, and optionally per hour within a date, so tests can
place a matching window somewhere other than the day's peak — which is the case the
Pipeline Run's best-matching-hour rule exists to handle.

`no_sleep` and `ingest` live here rather than in each suite. Both were declared twice,
verbatim, in a file whose own docstring promised shared fixtures — so the two copies could
drift and one suite would exercise a different pipeline entry point from the other.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from nazarenow.pipeline import run_pipeline
from nazarenow.sources.open_meteo import TIMEZONE

SWELL_HEIGHT_BONUS_M = 0.9
BONUS_HOUR = 4


def swell_height_for(significant_wave_height: float, hour: int) -> float:
    """The swell height this fixture generates for an hour of a given sea.

    Swell height varies independently of Significant Wave Height, and on one hour a day it
    varies *more*, so a model reading the wrong variable is detectable. Until #13 nothing
    read it and 04:00 was inert; the learned model reads both, so that hour now genuinely
    carries the day's largest predicted sea on an otherwise uniform day and wins the
    tie-break on merit.

    That makes this arithmetic something tests need to name, and it lives here — beside the
    only code that generates it — because a test re-deriving the same expression would go on
    agreeing with a changed fixture only by luck.
    """
    bonus = SWELL_HEIGHT_BONUS_M if hour == BONUS_HOUR else 0.0
    return round(significant_wave_height * 0.8 + bonus, 2)


# A flat, onshore, short-period day. Fails every condition of the rule.
#
# The wind speed has to sit **above** `light_wind_exemption_kmh` to fail. Since ADR 0009 a
# wind below the exemption holds the condition whatever its direction, so the old 14 km/h
# from 260° now passes and this fixture would quietly stop failing every condition while
# still being named as though it did.
QUIET = {
    "significant_wave_height": 0.9,
    "swell_period": 7.0,
    "swell_direction": 250,
    "wind_speed": 22.0,
    "wind_direction": 260,
}

# Clears every condition comfortably.
#
# Its wind is deliberately above the exemption too, so this exercises the *offshore* branch
# of the condition rather than the light-wind one. A day that passes only because the air is
# still is a different day from one groomed by an offshore breeze, and this fixture is meant
# to be the second.
GIANT = {
    "significant_wave_height": 4.2,
    "swell_period": 16.5,
    "swell_direction": 298,
    "wind_speed": 18.0,
    "wind_direction": 110,
}

MARINE_UNITS = {
    "time": "iso8601",
    "wave_height": "m",
    "wave_direction": "°",
    "wave_period": "s",
    "swell_wave_height": "m",
    "swell_wave_direction": "°",
    "swell_wave_period": "s",
    "sea_surface_temperature": "°C",
}

WEATHER_UNITS = {
    "time": "iso8601",
    "temperature_2m": "°C",
    "wind_speed_10m": "km/h",
    "wind_direction_10m": "°",
}


def no_sleep(_seconds: float) -> None:
    """Backoff is real behaviour, but waiting for it makes the suite slow enough that
    people stop running it."""


# How far each wave model sits from the day's base conditions, in metres of swell height.
#
# Chosen so the three *organisations* land at 0.00, 0.15 and 0.30 rather than the five models
# landing anywhere convenient: DWD's two members straddle its vote and NCEP's two agree with
# each other, so a fixture built this way fails if `by_provider` ever stops collapsing an
# organisation to one opinion. The resulting swell-height spread is 0.30 m at every hour.
ENSEMBLE_OFFSETS = {
    "meteofrance_wave": 0.0,
    "dwd_ewam": 0.1,
    "dwd_gwam": 0.2,
    "ncep_gfswave025": 0.3,
    "ncep_gfswave016": 0.3,
}

ENSEMBLE_SPREAD_M = 0.3
"""The swell-height Model Spread `forecast_provider` produces, named so tests do not
re-derive it from `ENSEMBLE_OFFSETS` and go on agreeing with a changed fixture by luck."""


def forecast_provider(
    by_date: dict[str, dict[str, float]] | None = None,
    today: str = "2026-02-09",
    days: int = 14,
    only_hours: dict[str, tuple[int, ...]] | None = None,
    peak_but_onshore: dict[str, tuple[int, ...]] | None = None,
    also_hours: dict[str, tuple[dict[str, float], tuple[int, ...]]] | None = None,
    silent_models: tuple[str, ...] = (),
    ensemble_status: int = 200,
) -> httpx.MockTransport:
    """A provider returning `days` days from `today`, quiet except where overridden.

    `only_hours` restricts a date's overridden conditions to those hours, leaving the
    rest of the day quiet. Without it a day is uniform, which cannot distinguish a rule
    judging the best matching hour from one judging the peak or the first.

    `also_hours` overlays a *second*, different set of conditions onto named hours of a
    date, as `{date: (conditions, hours)}`. A day needs two genuinely different windows to
    show which one a call was judged on — one clean but modest, one large but failing a
    different condition. With a single window every rule for choosing an hour agrees.

    The same transport also answers the ensemble request Model Spread is measured from,
    recognised by its `models` parameter. `silent_models` makes named members answer null
    for every hour, which is how a provider is unavailable rather than absent; a non-200
    `ensemble_status` makes the endpoint itself fail, which ADR 0003 requires to degrade the
    estimate rather than the run.
    """
    by_date = by_date or {}
    only_hours = only_hours or {}
    peak_but_onshore = peak_but_onshore or {}
    also_hours = also_hours or {}
    start = date.fromisoformat(today)
    stamps: list[str] = []
    marine: dict[str, list[Any]] = {name: [] for name in MARINE_UNITS if name != "time"}
    weather: dict[str, list[Any]] = {name: [] for name in WEATHER_UNITS if name != "time"}

    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        override = by_date.get(day, {})
        window = only_hours.get(day)

        biggest = peak_but_onshore.get(day, ())
        overlay = also_hours.get(day)
        for hour in range(24):
            applies = override and (window is None or hour in window)
            conditions = {**QUIET, **(override if applies else {})}
            if overlay is not None and hour in overlay[1]:
                conditions = {**conditions, **overlay[0]}
            if hour in biggest:
                # The day's largest sea, but blowing onshore: a peak that fails the
                # rule, so judging the peak differs from judging the best match.
                conditions = {
                    **conditions,
                    "significant_wave_height": conditions["significant_wave_height"] + 3.0,
                    "wind_direction": 270,
                }
            stamps.append(f"{day}T{hour:02d}:00")

            # `significant_wave_height` is the rule's height input and ADR 0002's Proxy
            # Target; swell height is a different variable and varies independently so a
            # model reading the wrong one is detectable.
            marine["wave_height"].append(conditions["significant_wave_height"])
            marine["swell_wave_height"].append(
                swell_height_for(conditions["significant_wave_height"], hour)
            )
            marine["swell_wave_period"].append(conditions["swell_period"])
            marine["swell_wave_direction"].append(conditions["swell_direction"])
            marine["wave_period"].append(conditions["swell_period"] - 2.0)
            marine["wave_direction"].append((conditions["swell_direction"] + 30) % 360)
            marine["sea_surface_temperature"].append(15.0)
            weather["temperature_2m"].append(13.0)
            weather["wind_speed_10m"].append(conditions["wind_speed"])
            weather["wind_direction_10m"].append(conditions["wind_direction"])

    marine_body = {
        "latitude": 39.541664,
        "longitude": -9.208328,
        # Nazaré's own clock, which is what the run asks for and checks — a day here is a
        # day a traveller stands on the beach, not a UTC day (ADR 0008).
        "timezone": TIMEZONE,
        "current_units": MARINE_UNITS,
        "current": {"time": stamps[0], **{k: v[0] for k, v in marine.items()}},
        "hourly_units": MARINE_UNITS,
        "hourly": {"time": stamps, **marine},
    }
    weather_body = {
        "latitude": 39.5,
        "longitude": -9.1875,
        "timezone": TIMEZONE,
        "current_units": WEATHER_UNITS,
        "current": {"time": stamps[0], **{k: v[0] for k, v in weather.items()}},
        "hourly_units": WEATHER_UNITS,
        "hourly": {"time": stamps, **weather},
    }

    ensemble_body = ensemble_body_from(marine_body, silent_models=silent_models)

    def handle(request: httpx.Request) -> httpx.Response:
        if is_ensemble_request(request):
            if ensemble_status != 200:
                return httpx.Response(ensemble_status, json={"reason": "unavailable"})
            return httpx.Response(200, json=ensemble_body)
        marine_request = "marine" in request.url.host
        return httpx.Response(200, json=marine_body if marine_request else weather_body)

    return httpx.MockTransport(handle)


def is_ensemble_request(request: httpx.Request) -> bool:
    """Whether this is the request Model Spread is measured from.

    The ensemble goes to the same marine host as the single-model forecast, so the `models`
    parameter is what tells the two apart rather than the URL. Every stubbed provider in the
    suite needs to answer it: a Pipeline Run now makes three requests, and a transport that
    hands the single-model body back for the ensemble is not simulating a degraded provider —
    it is simulating a contract change, which fails the run for a reason the test never meant.
    """
    return "models" in request.url.params


def ensemble_body_from(
    marine_body: dict[str, Any], *, silent_models: tuple[str, ...] = ()
) -> dict[str, Any]:
    """One series per model per variable, built from a marine body's own hourly arrays.

    That is the shape Open-Meteo answers a comma-separated `models` list in, and deriving it
    from the marine body rather than assembling it independently means a fixture cannot move
    one of the two and leave the other describing a different sea.

    `silent_models` answer null for every hour — present in the payload and carrying nothing,
    which is what an unavailable member actually looks like and is why a 200 alone proves a
    model agreed with nobody.

    A marine body deliberately broken to exercise a rejection path is copied as far as it
    goes and no further. Those runs fail on the marine response, which is fetched first, so
    the ensemble is never requested — but this is built when the transport is constructed,
    and raising here would turn "the marine payload was rejected" into a fixture error.
    """
    hourly = marine_body.get("hourly") or {}
    series: dict[str, list[Any]] = {"time": hourly.get("time", [])}
    units: dict[str, str] = {"time": "iso8601"}

    for model, offset in ENSEMBLE_OFFSETS.items():
        silent = model in silent_models
        for variable, shift in (
            ("swell_wave_height", offset),
            ("swell_wave_period", offset * 2),
            ("swell_wave_direction", offset * 10),
        ):
            if variable not in hourly:
                continue
            # Bearings wrap, as the provider's own do. Without this a base direction of
            # 358° produces members at 360° and 361°, which no marine API would ever
            # return — and a fixture that cannot cross north cannot exercise the case
            # circular spread exists for.
            wrap = 360 if variable.endswith("direction") else None
            series[f"{variable}_{model}"] = [
                None
                if silent or value is None
                else round((value + shift) % wrap if wrap else value + shift, 4)
                for value in hourly[variable]
            ]
            units[f"{variable}_{model}"] = MARINE_UNITS[variable]

    return {
        "latitude": marine_body.get("latitude", 39.541664),
        "longitude": marine_body.get("longitude", -9.208328),
        "timezone": marine_body.get("timezone", TIMEZONE),
        "hourly_units": units,
        "hourly": series,
    }


def ingest(store, transport: httpx.MockTransport, sleep=no_sleep) -> None:
    with httpx.Client(transport=transport) as http:
        run_pipeline(store, http, sleep=sleep)


def stub_hours(date: str, conditions: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """A day of forecast hours in the shape the store holds them.

    Bypasses the provider and the Pipeline Run, which is the point: a run always stores
    calls alongside its forecast, and the call record is append-only, so no sequence of
    real runs can produce a stored forecast with no calls behind it. The API must still
    answer honestly if it ever meets one.
    """
    readings = {**QUIET, **(conditions or {})}
    return [
        {
            "at": f"{date}T{hour:02d}:00",
            "readings": {
                "swell_height": {"value": readings["significant_wave_height"] * 0.8, "unit": "m"},
                "swell_period": {"value": readings["swell_period"], "unit": "s"},
                "swell_direction": {"value": readings["swell_direction"], "unit": "°"},
                "significant_wave_height": {
                    "value": readings["significant_wave_height"],
                    "unit": "m",
                },
                "wave_period": {"value": readings["swell_period"] - 2.0, "unit": "s"},
                "wave_direction": {"value": readings["swell_direction"], "unit": "°"},
                "water_temperature": {"value": 15.0, "unit": "°C"},
                "air_temperature": {"value": 13.0, "unit": "°C"},
                "wind_speed": {"value": readings["wind_speed"], "unit": "km/h"},
                "wind_direction": {"value": readings["wind_direction"], "unit": "°"},
            },
        }
        for hour in range(24)
    ]
