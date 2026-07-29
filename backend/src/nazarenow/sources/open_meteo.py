"""Fetching Offshore Conditions from Open-Meteo.

Two endpoints are needed: the marine API for swell and sea surface temperature, and the
forecast API for wind and air temperature. Both are free and need no key.

Everything here is deliberately suspicious of the provider. Ticket #2 established that
this project's characteristic failure is data that arrives looking plausible and is
wrong — a download that silently returned 30 days instead of 16 years, a depth level
that silently returned an empty column. So responses are validated on arrival and a
missing field or missing unit fails the run rather than becoming a null in the store.
"""

from __future__ import annotations

import math
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

# The provider variable behind each reading name. One mapping, so a reading cannot be
# requested without being collected or collected without being requested — they were
# previously two parallel lists agreeing only by coincidence, and drift would have
# raised a KeyError after raw responses had already been written.
MARINE_READINGS = {
    "swell_height": "swell_wave_height",
    "swell_period": "swell_wave_period",
    "swell_direction": "swell_wave_direction",
    "significant_wave_height": "wave_height",
    "wave_period": "wave_period",
    "wave_direction": "wave_direction",
    "water_temperature": "sea_surface_temperature",
}

WEATHER_READINGS = {
    "air_temperature": "temperature_2m",
    "wind_speed": "wind_speed_10m",
    "wind_direction": "wind_direction_10m",
}

MARINE_VARIABLES = sorted(set(MARINE_READINGS.values()))
WEATHER_VARIABLES = sorted(set(WEATHER_READINGS.values()))

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
# However long a provider asks us to wait, a Pipeline Run must still finish. An unbounded
# Retry-After of "inf" previously hung the run forever. The cap is generous enough to
# honour a real rate-limit pause — Open-Meteo's daily limit resets are minutes, not
# seconds — rather than ignoring the provider's instruction and hammering it early.
#
# Worst case for a whole Pipeline Run: two retries per endpoint, two endpoints, so about
# twenty minutes if both sources stall at the cap. Ticket #7's scheduler interval must
# exceed that, or runs will overlap.
MAX_BACKOFF_SECONDS = 300.0


class OpenMeteoResponse(BaseModel):
    latitude: float
    longitude: float
    current_units: dict[str, str]
    current: dict[str, Any]


def is_rate_limited(response: httpx.Response) -> bool:
    """Whether the provider is refusing us for quota reasons rather than correctness.

    Open-Meteo signals quota exhaustion with 429, but has also been observed returning
    a 4xx whose body carries a "limit exceeded" reason. Treating that as a permanent
    client error would turn a wait-and-retry condition into a hard failure.
    """
    if response.status_code == 429:
        return True
    if response.status_code >= 400:
        try:
            reason = str(response.json().get("reason", ""))
        except Exception:  # noqa: BLE001 — a non-JSON error body is simply not this case
            return False
        return "limit" in reason.lower()
    return False


def retry_delay(response: httpx.Response, attempt: int) -> float:
    """How long to wait before retrying, honouring Retry-After within sane bounds.

    The header is attacker-adjacent input: it has arrived as a negative number, as
    "nan", and as values large enough to stall the run indefinitely. Anything not a
    finite, non-negative number falls back to linear backoff, and everything is capped.
    """
    header = response.headers.get("Retry-After")
    delay = BACKOFF_SECONDS * attempt
    if header:
        try:
            parsed = float(header)
        except ValueError:
            parsed = math.nan  # HTTP-date form; fall back to linear backoff
        if math.isfinite(parsed) and parsed >= 0:
            delay = parsed
    return min(max(delay, 0.0), MAX_BACKOFF_SECONDS)


def validate(body: dict[str, Any], variables: list[str]) -> None:
    """Reject a response that does not carry every variable we asked for, with a unit.

    A silently absent field would become a missing reading on the page, which looks
    like calm conditions rather than like a fault.
    """
    try:
        parsed = OpenMeteoResponse.model_validate(body)
    except ValidationError as error:
        raise ValueError(f"Unexpected Open-Meteo payload: {error}") from error

    if "time" not in parsed.current:
        raise ValueError("Open-Meteo response has no observation time")

    missing = [name for name in variables if name not in parsed.current]
    if missing:
        raise ValueError(f"Open-Meteo response is missing requested variables: {missing}")

    without_units = [name for name in variables if name not in parsed.current_units]
    if without_units:
        raise ValueError(f"Open-Meteo response is missing units for: {without_units}")


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

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Only transport failures are caught here. Catching HTTPError around
        # raise_for_status as well would swallow HTTPStatusError and retry it, which
        # silently retried 400s and 404s three times each — permanent errors, retried at
        # the cost of the provider's rate budget and two pointless backoff sleeps.
        try:
            response = client.get(url, params=params, timeout=30)
        except httpx.HTTPError:
            if attempt == MAX_ATTEMPTS:
                raise
            sleep(min(BACKOFF_SECONDS * attempt, MAX_BACKOFF_SECONDS))
            continue

        # A 5xx may be transient and a rate limit will pass. Every other error status is
        # the provider telling us we are wrong, and asking again will not change its mind.
        retryable = response.status_code >= 500 or is_rate_limited(response)
        if retryable and attempt < MAX_ATTEMPTS:
            sleep(retry_delay(response, attempt))
            continue

        # Covers 3xx as well as 4xx and 5xx: anything that is not a success stops here
        # rather than reaching json() and failing as a confusing parse error.
        response.raise_for_status()

        body = response.json()
        validate(body, variables)
        return body, str(response.url)

    # Unreachable: the final attempt either returns or raises above.
    raise AssertionError("retry loop completed without returning or raising")


def fetch_marine(client: httpx.Client, sleep=time.sleep) -> tuple[dict[str, Any], str]:
    return fetch(client, MARINE_URL, MARINE_VARIABLES, sleep)


def fetch_weather(client: httpx.Client, sleep=time.sleep) -> tuple[dict[str, Any], str]:
    return fetch(client, WEATHER_URL, WEATHER_VARIABLES, sleep)
