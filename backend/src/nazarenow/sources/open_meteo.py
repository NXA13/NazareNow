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

# Timestamps arrive on Nazaré's own clock, not UTC.
#
# A day in this system is a day a traveller stands on the beach (CONTEXT.md, ADR 0008), and
# Europe/Lisbon is UTC only in winter — under summer time the hour stamped 23:00 UTC is
# already midnight in Nazaré. Grouping UTC stamps by date therefore puts an hour of every
# such day on the wrong date, which decides what a call is issued *for*.
#
# Asking the provider for local time means the timestamps are already right and `days.py`
# can slice them, rather than the correctness resting on a conversion each reader has to
# remember to apply. About 28 days of every Big-Wave Season are affected, 25 of them in the
# first three weeks of October — which is when the deployment starts collecting.
TIMEZONE = "Europe/Lisbon"

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
    timezone: str
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

    # The zone the timestamps are on, checked rather than assumed. `timezone` is sent on
    # every request, but a request is a preference and only the response is evidence — the
    # same reasoning `EXPECTED_UNITS` applies below. A provider-side default that ignored
    # the parameter would shift every day boundary by an hour, and nothing downstream could
    # tell: a whole day's calls would be attributed to the wrong date while every number on
    # the page still looked entirely plausible.
    if parsed.timezone != TIMEZONE:
        raise ValueError(
            f"Open-Meteo returned timestamps on {parsed.timezone!r}; this system groups "
            f"hours into days on {TIMEZONE!r} and would put them on the wrong date"
        )

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
        "timezone": TIMEZONE,
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


# The readings Model Spread is measured on: the three the Heuristic Baseline decides a day
# by. Spread in anything else would be measuring doubt no tier consults.
#
# A mapping in the same shape as `MARINE_READINGS` and for the same reason — one place says
# which provider variable stands behind each name — and because everything downstream of the
# fetch works in this system's own vocabulary. `forecast_hour` already stores `swell_height`
# rather than `swell_wave_height`; a Model Spread stored under the provider's spelling would
# have made the store speak two languages and left something in the read path translating.
SPREAD_READINGS = {
    "swell_height": "swell_wave_height",
    "swell_period": "swell_wave_period",
    "swell_direction": "swell_wave_direction",
    # Combined Sea, added by #15. The Swell partition is what the tier conditions are judged
    # on, and Combined Sea is what the Predictive Distribution perturbs — the Amplification
    # Model reads it at a standardised coefficient of 1.09 against 0.09 or less for every
    # other feature. So a distribution widened by the partition's disagreement would leave
    # its dominant input fixed at one provider's number and report the ensemble as nearly
    # unanimous whatever it actually said.
    #
    # It is also the partition `analysis/model_spread/alignment.py` measured the ensemble on,
    # because the archive carries `_previous_dayN` for Combined Sea alone — so the figures
    # that justify combining these terms are measured on the variable being combined, rather
    # than carried across by argument as finding 4 had to.
    #
    # Free at the transport: one more variable on the request `fetch_ensemble` already makes,
    # not a second request.
    "significant_wave_height": "wave_height",
}

SPREAD_VARIABLES = sorted(set(SPREAD_READINGS.values()))


def fetch_ensemble(
    client: httpx.Client, models: list[str], sleep=time.sleep
) -> tuple[dict[str, Any], str]:
    """Every wave model's forecast, in one request, for Model Spread (#8, ADR 0003).

    **One request, not one per model.** Open-Meteo accepts a comma-separated `models` list
    and answers with one series per model per variable, suffixed with the model name. That
    matters for more than the request budget: every member is then read from a single
    response at a single instant, so none of the measured disagreement is our own sampling
    drifting between calls. It does not fix the members' own publication cadences —
    `analysis/model_spread/` measures what that costs and finds it inflates the spread,
    which errs toward caution.

    Deliberately **not** routed through `validate`. That function fails the run on a missing
    or null variable, which is right for the forecast the site displays and wrong here: ADR
    0003 says a provider being unavailable must degrade the uncertainty estimate rather than
    fail the Pipeline Run. A member returning nulls is an ensemble with fewer votes, and
    `spread.derive` is what decides whether enough are left.

    No `current` block is requested. Model Spread is about dates ahead, and asking for
    current conditions per model would add a second way for this call to fail for something
    the caller never reads.
    """
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(SPREAD_VARIABLES),
        "models": ",".join(models),
        "forecast_days": FORECAST_DAYS,
        "timezone": TIMEZONE,
        **UNIT_PARAMS,
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(MARINE_URL, params=params, timeout=30)
        except httpx.HTTPError:
            if attempt == MAX_ATTEMPTS:
                raise
            sleep(min(BACKOFF_SECONDS * attempt, MAX_BACKOFF_SECONDS))
            continue

        retryable = response.status_code >= 500 or is_rate_limited(response)
        if retryable and attempt < MAX_ATTEMPTS:
            sleep(retry_delay(response, attempt))
            continue

        response.raise_for_status()
        body = response.json()
        validate_ensemble(body, models)
        return body, str(response.url)

    raise RuntimeError("unreachable: the retry loop returns or raises")  # pragma: no cover


def validate_ensemble(body: dict[str, Any], models: list[str]) -> None:
    """Check only what a degraded ensemble still has to get right.

    Three things, and no more. The timestamps must be on the zone this system groups days
    by, or every date is off by an hour and nothing downstream could tell. The units must be
    the ones the thresholds are named in, for the reason `validate_units` gives. And the
    response must carry a time axis and at least one model's series, because a body with
    neither is a fault rather than an unavailable provider.

    What it does *not* check is that every model answered. That is the whole point: ADR 0003
    requires a missing provider to degrade Model Spread visibly rather than stop the run.
    """
    hourly = body.get("hourly") or {}
    if not hourly.get("time"):
        raise ValueError("Open-Meteo ensemble response has no time axis")

    if body.get("timezone") != TIMEZONE:
        raise ValueError(
            f"Open-Meteo returned ensemble timestamps on {body.get('timezone')!r}; this "
            f"system groups hours into days on {TIMEZONE!r} and would put them on the "
            "wrong date"
        )

    # Each series carried alongside the base variable it came from, rather than recovered
    # from the key by splitting on underscores. Model names contain them — `dwd_gwam`,
    # `meteofrance_wave` — so a split would sometimes strip half a model name and look up a
    # unit for a variable that does not exist.
    present = [
        (f"{variable}_{model}", variable)
        for model in models
        for variable in SPREAD_VARIABLES
        if f"{variable}_{model}" in hourly
    ]
    if not present:
        raise ValueError(
            f"Open-Meteo ensemble response carries no series for any of {models}; every "
            "member absent is a contract change, not an unavailable provider"
        )

    # A series must line up with the time axis it is read against. Length is not checked to
    # be strict about completeness — a member is entirely free to answer for none of these
    # hours — but a series that is *present* and short does not report less, it reports the
    # wrong hours: every reading past the gap is attributed to a timestamp it does not
    # belong to, and a date's spread is then measured across two different moments. That is
    # a payload that has changed shape, which fails a run here as it does everywhere else.
    axis = len(hourly["time"])
    ragged = {key: len(hourly[key]) for key, _ in present if len(hourly[key]) != axis}
    if ragged:
        raise ValueError(
            f"Open-Meteo ensemble series disagree in length with the time axis "
            f"({axis} hours): {ragged}"
        )

    # Every series that answered must say what it answered in. The check was previously
    # skipped for a series carrying no declared unit at all, which is the one case where the
    # scale is genuinely unknown — so the reading most in need of checking was the one
    # exempt from it, and it would have been stored under this system's assumed unit.
    units = body.get("hourly_units") or {}
    wrong = {
        key: units.get(key)
        for key, variable in present
        if units.get(key) != EXPECTED_UNITS[variable]
    }
    if wrong:
        raise ValueError(
            f"Open-Meteo returned ensemble units {wrong}; Model Spread is measured in the "
            "metres, seconds and degrees the thresholds are named in"
        )
