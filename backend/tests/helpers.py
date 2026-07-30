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

# A flat, onshore, short-period day. Fails every condition of the rule.
QUIET = {
    "significant_wave_height": 0.9,
    "swell_period": 7.0,
    "swell_direction": 250,
    "wind_speed": 14.0,
    "wind_direction": 260,
}

# Clears every condition comfortably.
GIANT = {
    "significant_wave_height": 4.2,
    "swell_period": 16.5,
    "swell_direction": 298,
    "wind_speed": 11.0,
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


def forecast_provider(
    by_date: dict[str, dict[str, float]] | None = None,
    today: str = "2026-02-09",
    days: int = 14,
    only_hours: dict[str, tuple[int, ...]] | None = None,
    peak_but_onshore: dict[str, tuple[int, ...]] | None = None,
) -> httpx.MockTransport:
    """A provider returning `days` days from `today`, quiet except where overridden.

    `only_hours` restricts a date's overridden conditions to those hours, leaving the
    rest of the day quiet. Without it a day is uniform, which cannot distinguish a rule
    judging the best matching hour from one judging the peak or the first.
    """
    by_date = by_date or {}
    only_hours = only_hours or {}
    peak_but_onshore = peak_but_onshore or {}
    start = date.fromisoformat(today)
    stamps: list[str] = []
    marine: dict[str, list[Any]] = {name: [] for name in MARINE_UNITS if name != "time"}
    weather: dict[str, list[Any]] = {name: [] for name in WEATHER_UNITS if name != "time"}

    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        override = by_date.get(day, {})
        window = only_hours.get(day)

        biggest = peak_but_onshore.get(day, ())
        for hour in range(24):
            applies = override and (window is None or hour in window)
            conditions = {**QUIET, **(override if applies else {})}
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
                round(conditions["significant_wave_height"] * 0.8 + (0.9 if hour == 4 else 0.0), 2)
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
        "current_units": MARINE_UNITS,
        "current": {"time": stamps[0], **{k: v[0] for k, v in marine.items()}},
        "hourly_units": MARINE_UNITS,
        "hourly": {"time": stamps, **marine},
    }
    weather_body = {
        "latitude": 39.5,
        "longitude": -9.1875,
        "current_units": WEATHER_UNITS,
        "current": {"time": stamps[0], **{k: v[0] for k, v in weather.items()}},
        "hourly_units": WEATHER_UNITS,
        "hourly": {"time": stamps, **weather},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        marine_request = "marine" in request.url.host
        return httpx.Response(200, json=marine_body if marine_request else weather_body)

    return httpx.MockTransport(handle)


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
