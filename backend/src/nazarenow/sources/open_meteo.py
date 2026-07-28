"""Fetching Offshore Conditions from Open-Meteo.

Two endpoints are needed: the marine API for swell and sea surface temperature, and the
forecast API for wind and air temperature. Both are free and need no key.

Everything here is deliberately suspicious of the provider. Ticket #2 established that
this project's characteristic failure is data that arrives looking plausible and is
wrong — a download that silently returned 30 days instead of 16 years, a depth level
that silently returned an empty column. So responses are validated on arrival and a
missing or unexpected field fails the run rather than becoming a null in the store.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Monican02's position: ~15 km offshore near the canyon head. Chosen deliberately over
# the beach itself — it is the location of the Proxy Target (ADR 0002), so what the site
# displays and what the model is eventually trained against describe the same water.
LATITUDE = 39.56
LONGITUDE = -9.21

MARINE_VARIABLES = [
    "wave_height",
    "wave_direction",
    "wave_period",
    "swell_wave_height",
    "swell_wave_direction",
    "swell_wave_period",
    "sea_surface_temperature",
]

WEATHER_VARIABLES = [
    "temperature_2m",
    "wind_speed_10m",
    "wind_direction_10m",
]

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0


class CurrentBlock(BaseModel):
    """The subset of a response we depend on. Extra fields are permitted and ignored."""

    time: str


class OpenMeteoResponse(BaseModel):
    latitude: float
    longitude: float
    current_units: dict[str, str]
    current: dict[str, Any]


def fetch(
    client: httpx.Client, url: str, variables: list[str], sleep=time.sleep
) -> tuple[dict[str, Any], str]:
    """GET one Open-Meteo endpoint, retrying transient failures with backoff.

    Returns the parsed body and the URL it came from. Raises on a payload that does not
    match the expected shape, so a provider changing its contract stops the run instead
    of quietly producing conditions with holes in them.
    """
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": ",".join(variables),
        "timezone": "UTC",
    }

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(url, params=params, timeout=30)
            # 429 carries a Retry-After we are obliged to honour; 5xx is worth retrying.
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < MAX_ATTEMPTS:
                sleep(retry_delay(response, attempt))
                continue
            response.raise_for_status()
        except httpx.HTTPError as error:
            last_error = error
            if attempt == MAX_ATTEMPTS:
                raise
            sleep(BACKOFF_SECONDS * attempt)
            continue

        body = response.json()
        validate(body, variables)
        return body, str(response.url)

    raise last_error or httpx.HTTPError(f"{url} failed after {MAX_ATTEMPTS} attempts")


def retry_delay(response: httpx.Response, attempt: int) -> float:
    """Honour Retry-After when the provider sets it, otherwise back off linearly."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return BACKOFF_SECONDS * attempt


def validate(body: dict[str, Any], variables: list[str]) -> None:
    """Reject a response that does not carry every variable we asked for.

    A silently absent field would become a missing reading on the page, which looks like
    calm conditions rather than like a fault.
    """
    try:
        parsed = OpenMeteoResponse.model_validate(body)
        CurrentBlock.model_validate(parsed.current)
    except ValidationError as error:
        raise ValueError(f"Unexpected Open-Meteo payload: {error}") from error

    missing = [name for name in variables if name not in parsed.current]
    if missing:
        raise ValueError(f"Open-Meteo response is missing requested variables: {missing}")

    without_units = [name for name in variables if name not in parsed.current_units]
    if without_units:
        raise ValueError(f"Open-Meteo response is missing units for: {without_units}")


def fetch_marine(client: httpx.Client, sleep=time.sleep) -> tuple[dict[str, Any], str]:
    return fetch(client, MARINE_URL, MARINE_VARIABLES, sleep)


def fetch_weather(client: httpx.Client, sleep=time.sleep) -> tuple[dict[str, Any], str]:
    return fetch(client, WEATHER_URL, WEATHER_VARIABLES, sleep)
