"""A Pipeline Run: fetch Offshore Conditions, validate them, store them.

Per ADR 0005 this is the only part of the system that contacts a third party. The API
and the web interface read what this leaves behind.

Ordering matters. A response is validated before it is stored, so a payload that has
changed shape fails the run rather than entering the store. Parsed conditions are
written only once every source has been fetched and validated — a run that fails
partway leaves the previous run's conditions in place rather than a half-updated
picture.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from nazarenow.sources import open_meteo
from nazarenow.sources.open_meteo import MARINE_READINGS, WEATHER_READINGS
from nazarenow.store import Store


def collect(body: dict[str, Any], mapping: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Pull the readings we care about, each carrying the provider's own unit.

    Indexing directly is safe because `validate` has already established that every
    mapped variable and its unit are present — and the mapping here is the same object
    the request was built from, so the two cannot drift apart.
    """
    current = body["current"]
    units = body["current_units"]
    return {
        name: {"value": current[source], "unit": units[source]} for name, source in mapping.items()
    }


def collect_hourly(
    body: dict[str, Any], mapping: dict[str, str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Readings for every forecast hour, keyed by timestamp.

    Validation has already established that every mapped variable is present, carries a
    unit, and has exactly as many values as the time axis — so zipping them here cannot
    misalign a reading against the wrong hour.
    """
    hourly = body["hourly"]
    units = body["hourly_units"]
    by_hour: dict[str, dict[str, dict[str, Any]]] = {}

    for index, stamp in enumerate(hourly["time"]):
        values = {name: hourly[source][index] for name, source in mapping.items()}
        # The provider pads its time axis to the requested range and fills the hours it
        # cannot model with nulls — marine data currently stops around nine days while
        # the axis runs to sixteen. Those hours are dropped rather than stored: a null
        # reading has no honest rendering, and a zero would draw a flat calm sea.
        if any(value is None for value in values.values()):
            continue
        by_hour[stamp] = {
            name: {"value": values[name], "unit": units[source]} for name, source in mapping.items()
        }

    return by_hour


def merge_hourly(
    marine: dict[str, dict[str, dict[str, Any]]],
    weather: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """One record per hour both providers cover.

    Only hours present in both are kept. An hour with half its readings would render as
    a gap-toothed row that looks like calm weather rather than like missing data.
    """
    return [
        {"at": stamp, "readings": marine[stamp] | weather[stamp]}
        for stamp in sorted(set(marine) & set(weather))
    ]


def earliest(*timestamps: str) -> str:
    """The oldest of several observation times.

    The two endpoints are separate products and each reports its own observation time.
    Presenting ten readings under the marine timestamp alone would overstate how fresh
    the weather half is, so the conditions are dated by the older of the two: the whole
    picture is at least this old.
    """
    return min(timestamps)


def run_pipeline(store: Store, client: httpx.Client, sleep=time.sleep) -> None:
    """Execute one Pipeline Run against the given store."""
    marine_body, marine_url = open_meteo.fetch_marine(client, sleep)
    store.record_raw_response("open-meteo-marine", marine_url, marine_body)

    weather_body, weather_url = open_meteo.fetch_weather(client, sleep)
    store.record_raw_response("open-meteo-weather", weather_url, weather_body)

    readings = collect(marine_body, MARINE_READINGS) | collect(weather_body, WEATHER_READINGS)

    store.record_conditions(
        observed_at=earliest(marine_body["current"]["time"], weather_body["current"]["time"]),
        latitude=marine_body["latitude"],
        longitude=marine_body["longitude"],
        readings=readings,
    )

    hours = merge_hourly(
        collect_hourly(marine_body, MARINE_READINGS),
        collect_hourly(weather_body, WEATHER_READINGS),
    )
    if not hours:
        # A response that parses but yields no usable hour is a provider fault, not an
        # empty forecast. Storing it would delete a good forecast and leave the page
        # saying no run had happened — blaming absence for a successful-looking run that
        # destroyed nine real days. ADR 0005 promises stale-but-honest instead.
        raise ValueError(
            "Providers returned no usable forecast hours; keeping the previous forecast"
        )
    store.replace_forecast(hours)
