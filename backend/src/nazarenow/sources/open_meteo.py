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

# The unit each variable must arrive in, checked on every response.
#
# The Heuristic Baseline compares bare floats against thresholds named in metres, seconds
# and km/h, and prints those unit names into the reasons a user reads. Nothing connected
# the provider's declared unit to the one the rule assumes: units were carried through for
# display and dropped before any decision used them, and validation only checked that a
# unit *existed*. A response declaring every marine unit as "furlongs" was accepted, and a
# provider default flipping km/h to m/s would have applied a 35 km/h threshold to a value
# in m/s — a Go Call issued through a 126 km/h gale, with "35 km/h" written beside it.
#
# Requesting units explicitly (below) stops a default from drifting. Checking the response
# stops a drift we did not anticipate. Both are needed: the request is a preference, and
# only the response is evidence.
EXPECTED_UNITS = {
    "wave_height": "m",
    "swell_wave_height": "m",
    "swell_wave_period": "s",
    "swell_wave_direction": "°",
    "wave_period": "s",
    "wave_direction": "°",
    "sea_surface_temperature": "°C",
    "temperature_2m": "°C",
    "wind_speed_10m": "km/h",
    "wind_direction_10m": "°",
}

# Sent on every request so a provider-side default cannot change what arrives.
UNIT_PARAMS = {
    "temperature_unit": "celsius",
    "wind_speed_unit": "kmh",
    "length_unit": "metric",
}

# The provider returns sixteen days of hourly data in the same response as the current
# conditions, so the forecast range costs no additional requests against a free API.
FORECAST_DAYS = 16

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
    hourly_units: dict[str, str]
    hourly: dict[str, list[Any]]


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

    # Present but null is not present. Checking keys alone let `sea_surface_temperature:
    # null` through: it was committed to the store, the CLI then raised while formatting
    # it *after* the commit, and the API rejected the stored null so current conditions
    # returned 500 until the next good run. This module's docstring already promised a
    # missing field fails the run rather than becoming a null in the store — the hourly
    # path dropped nulls, and this one did not.
    null = [name for name in variables if parsed.current[name] is None]
    if null:
        raise ValueError(f"Open-Meteo response has null current readings for: {null}")

    without_units = [name for name in variables if name not in parsed.current_units]
    if without_units:
        raise ValueError(f"Open-Meteo response is missing units for: {without_units}")

    validate_units(parsed.current_units, variables, "current")
    validate_hourly(parsed, variables)


def validate_units(units: dict[str, str], variables: list[str], block: str) -> None:
    """Every variable must arrive in the unit the thresholds and labels assume.

    A unit that merely exists proves nothing. The rule of thumb compares bare numbers to
    thresholds named in metres, seconds and km/h, so a provider changing scale would not
    fail anything — it would quietly change what the thresholds mean while the interface
    kept printing the old unit name beside the new value.
    """
    wrong = {
        name: units[name]
        for name in variables
        if name in EXPECTED_UNITS and units.get(name) != EXPECTED_UNITS[name]
    }
    if wrong:
        expected = {name: EXPECTED_UNITS[name] for name in wrong}
        raise ValueError(
            f"Open-Meteo {block} block reports unexpected units {wrong}; "
            f"this system's thresholds and labels assume {expected}"
        )

    unknown = [name for name in variables if name not in EXPECTED_UNITS]
    if unknown:
        raise ValueError(
            f"No expected unit is declared for {unknown}, so their scale cannot be "
            "checked; add them to EXPECTED_UNITS before requesting them"
        )


def validate_hourly(parsed: OpenMeteoResponse, variables: list[str]) -> None:
    """The hourly block must carry every variable, with units, all the same length.

    Length matters more than it looks: a short array does not raise, it silently
    truncates the forecast or misaligns every reading against the wrong hour. That reads
    as data rather than as a fault, which is this project's characteristic failure.
    """
    if "time" not in parsed.hourly:
        raise ValueError("Open-Meteo hourly block has no time axis")

    missing = [name for name in variables if name not in parsed.hourly]
    if missing:
        raise ValueError(f"Open-Meteo hourly block is missing variables: {missing}")

    without_units = [name for name in variables if name not in parsed.hourly_units]
    if without_units:
        raise ValueError(f"Open-Meteo hourly block is missing units for: {without_units}")

    validate_units(parsed.hourly_units, variables, "hourly")

    axis = parsed.hourly["time"]
    if len(set(axis)) != len(axis):
        raise ValueError("Open-Meteo hourly time axis contains duplicate timestamps")

    expected = len(axis)
    wrong = {
        name: len(parsed.hourly[name]) for name in variables if len(parsed.hourly[name]) != expected
    }
    if wrong:
        raise ValueError(
            f"Open-Meteo hourly arrays disagree in length with the time axis "
            f"({expected} hours): {wrong}"
        )


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
        "hourly": ",".join(variables),
        "forecast_days": FORECAST_DAYS,
        "timezone": "UTC",
        # Explicit, so a provider-side default cannot silently change the scale the
        # thresholds are written against. Verified against the response as well.
        **UNIT_PARAMS,
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
