"""Shared fixtures for building stubbed provider responses.

Extracted so tests about calls can compose a forecast with chosen conditions on chosen
dates, without duplicating the marine/weather payload shapes.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from nazarenow.pipeline import run_pipeline

QUIET = {
    "swell_height": 0.9,
    "swell_period": 7.0,
    "swell_direction": 250,
    "wind_speed": 14.0,
    "wind_direction": 260,
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
) -> httpx.MockTransport:
    """A provider returning `days` days from `today`, quiet except where overridden.

    Conditions are constant within a day so that a day's summary is unambiguous; the
    hour-level variation the summary tests need lives in test_forecast.py's fixture.
    """
    by_date = by_date or {}
    start = date.fromisoformat(today)
    stamps: list[str] = []
    marine: dict[str, list[Any]] = {name: [] for name in MARINE_UNITS if name != "time"}
    weather: dict[str, list[Any]] = {name: [] for name in WEATHER_UNITS if name != "time"}

    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        conditions = {**QUIET, **by_date.get(day, {})}
        for hour in range(24):
            stamps.append(f"{day}T{hour:02d}:00")
            marine["swell_wave_height"].append(conditions["swell_height"])
            marine["swell_wave_period"].append(conditions["swell_period"])
            marine["swell_wave_direction"].append(conditions["swell_direction"])
            # Combined Sea peaks at its own hour, so a summary reading the wrong family
            # is detectable rather than silently identical.
            marine["wave_height"].append(conditions["swell_height"] + (1.4 if hour == 17 else 0.3))
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
