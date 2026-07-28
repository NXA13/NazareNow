"""A Pipeline Run: fetch Offshore Conditions, validate them, store them.

Per ADR 0005 this is the only part of the system that contacts a third party. The API
and the web interface read what this leaves behind.

Ordering matters. Raw responses are stored the moment they arrive, before anything
interprets them, so a provider changing shape can be diagnosed from what was actually
received. Parsed conditions are written only once every source has been fetched and
validated — a run that fails partway leaves the previous run's conditions in place
rather than a half-updated picture.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from nazarenow.sources import open_meteo
from nazarenow.store import Store

# Maps the provider's variable names onto the vocabulary in CONTEXT.md. The site should
# speak the project's language, not Open-Meteo's.
MARINE_READINGS = {
    "swell_height": "swell_wave_height",
    "swell_period": "swell_wave_period",
    "swell_direction": "swell_wave_direction",
    "wave_height": "wave_height",
    "wave_period": "wave_period",
    "wave_direction": "wave_direction",
    "water_temperature": "sea_surface_temperature",
}

WEATHER_READINGS = {
    "air_temperature": "temperature_2m",
    "wind_speed": "wind_speed_10m",
    "wind_direction": "wind_direction_10m",
}


def collect(body: dict[str, Any], mapping: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Pull the readings we care about, each carrying the provider's own unit."""
    current = body["current"]
    units = body["current_units"]
    return {
        name: {"value": current[source], "unit": units[source]} for name, source in mapping.items()
    }


def run_pipeline(store: Store, client: httpx.Client, sleep=time.sleep) -> None:
    """Execute one Pipeline Run against the given store."""
    marine_body, marine_url = open_meteo.fetch_marine(client, sleep)
    store.record_raw_response("open-meteo-marine", marine_url, marine_body)

    weather_body, weather_url = open_meteo.fetch_weather(client, sleep)
    store.record_raw_response("open-meteo-weather", weather_url, weather_body)

    readings = collect(marine_body, MARINE_READINGS) | collect(weather_body, WEATHER_READINGS)

    store.record_conditions(
        observed_at=marine_body["current"]["time"],
        latitude=marine_body["latitude"],
        longitude=marine_body["longitude"],
        readings=readings,
    )
