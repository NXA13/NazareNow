"""Ingestion through to the API, driven at the agreed backend seam.

A test stubs the third-party providers at the HTTP boundary, executes a Pipeline Run,
then reads the result back through the API. Ingestion, validation and the store are all
internal to this seam and may be restructured freely.

Counting requests that reach the stub is behaviour the system exhibits outwardly, so
asserting on it respects the seam even though the retry policy itself is internal.

Per ADR 0005 the request path must never contact a provider. conftest.py blocks outbound
sockets, so a test that reads the API without first running the pipeline would fail
loudly rather than quietly reaching the network.
"""

from __future__ import annotations

import concurrent.futures
import os
import sqlite3
from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

from nazarenow.api import CurrentConditions
from nazarenow.pipeline import run_pipeline
from nazarenow.sources.open_meteo import MARINE_READINGS, WEATHER_READINGS
from nazarenow.store import DEFAULT_DATABASE, Store, StoreUnavailable

# Fields on the response that describe the observation rather than being readings.
METADATA_FIELDS = {"observed_at", "fetched_at", "latitude", "longitude"}

MARINE_BODY = {
    "latitude": 39.541664,
    "longitude": -9.208328,
    "current_units": {
        "time": "iso8601",
        "wave_height": "m",
        "wave_direction": "°",
        "wave_period": "s",
        "swell_wave_height": "m",
        "swell_wave_direction": "°",
        "swell_wave_period": "s",
        "sea_surface_temperature": "°C",
    },
    "current": {
        "time": "2026-02-13T09:00",
        "wave_height": 8.4,
        "wave_direction": 295,
        "wave_period": 16.2,
        "swell_wave_height": 8.1,
        "swell_wave_direction": 298,
        "swell_wave_period": 17.0,
        "sea_surface_temperature": 15.2,
    },
}

WEATHER_BODY = {
    "latitude": 39.5,
    "longitude": -9.1875,
    "current_units": {
        "time": "iso8601",
        "temperature_2m": "°C",
        "wind_speed_10m": "km/h",
        "wind_direction_10m": "°",
    },
    "current": {
        "time": "2026-02-13T09:00",
        "temperature_2m": 13.4,
        "wind_speed_10m": 11.0,
        "wind_direction_10m": 115,
    },
}


def no_sleep(_seconds: float) -> None:
    """Backoff is real behaviour, but waiting for it makes the suite slow enough that
    people stop running it. Injected so the retry path is exercised at speed."""


def provider(marine=MARINE_BODY, weather=WEATHER_BODY):
    def handle(request: httpx.Request) -> httpx.Response:
        body = marine if "marine" in request.url.host else weather
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handle)


def failing_provider(status: int, headers: dict[str, str] | None = None, body=None):
    """A stub that records every request that reached it."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body or {"error": "nope"}, headers=headers or {})

    return httpx.MockTransport(handle), seen


def unreachable_provider():
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError("refused")

    return httpx.MockTransport(handle), seen


def ingest(store, transport, sleep=no_sleep) -> None:
    with httpx.Client(transport=transport) as http:
        run_pipeline(store, http, sleep=sleep)


# --- serving -----------------------------------------------------------------


def test_current_conditions_come_from_the_stored_pipeline_run(store, client) -> None:
    ingest(store, provider())

    body = client.get("/api/conditions/current").json()

    assert body["swell_height"] == {"value": 8.1, "unit": "m"}
    assert body["swell_period"] == {"value": 17.0, "unit": "s"}
    assert body["swell_direction"] == {"value": 298, "unit": "°"}
    assert body["significant_wave_height"] == {"value": 8.4, "unit": "m"}
    assert body["wave_period"] == {"value": 16.2, "unit": "s"}
    assert body["wave_direction"] == {"value": 295, "unit": "°"}
    assert body["wind_speed"] == {"value": 11.0, "unit": "km/h"}
    assert body["wind_direction"] == {"value": 115, "unit": "°"}
    assert body["air_temperature"] == {"value": 13.4, "unit": "°C"}
    assert body["water_temperature"] == {"value": 15.2, "unit": "°C"}


def test_conditions_are_dated_by_the_older_of_the_two_providers(store, client) -> None:
    """Two endpoints, two observation times. Presenting ten readings under the fresher
    of them would overstate how current half the page is."""
    stale_weather = {
        **WEATHER_BODY,
        "current": {**WEATHER_BODY["current"], "time": "2026-02-13T07:00"},
    }
    ingest(store, provider(weather=stale_weather))

    body = client.get("/api/conditions/current").json()

    assert body["observed_at"] == "2026-02-13T07:00"
    assert body["fetched_at"]


def test_no_conditions_yet_is_reported_rather_than_faked(client) -> None:
    """An empty store must not produce plausible-looking zeros."""
    response = client.get("/api/conditions/current")

    assert response.status_code == 503
    assert "no conditions" in response.json()["detail"].lower()


def test_concurrent_readers_all_see_the_stored_conditions(store, client) -> None:
    """The API is served from a threadpool, so the store is read concurrently.

    A single shared SQLite connection returned None for populated columns and raised
    IndexError from its statement cache under load — surfacing as the API reporting no
    conditions while holding conditions. Exactly the plausible-looking lie this project
    exists to avoid, and it never appears in a single-threaded test.
    """
    ingest(store, provider())

    def read(_: int) -> int:
        return client.get("/api/conditions/current").status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        statuses = Counter(pool.map(read, range(200)))

    assert statuses == {200: 200}, f"expected every read to succeed, got {dict(statuses)}"


# --- retention and validation -------------------------------------------------


def test_raw_provider_responses_are_retained(store) -> None:
    ingest(store, provider())

    raw = store.raw_responses()

    assert {entry["source"] for entry in raw} == {"open-meteo-marine", "open-meteo-weather"}
    assert all(entry["body"] for entry in raw)


def test_a_payload_missing_a_requested_variable_is_rejected(store, client) -> None:
    """A silently absent variable would render as a missing reading, which reads as calm
    conditions rather than as a fault."""
    without_swell = {
        **MARINE_BODY,
        "current": {k: v for k, v in MARINE_BODY["current"].items() if k != "swell_wave_height"},
    }

    with pytest.raises(ValueError, match="missing requested variables"):
        ingest(store, provider(marine=without_swell))

    assert client.get("/api/conditions/current").status_code == 503


def test_a_payload_missing_a_unit_is_rejected(store, client) -> None:
    """Units travel with values. A reading whose unit vanished cannot be displayed
    truthfully, so it must not be stored."""
    without_unit = {
        **MARINE_BODY,
        "current_units": {
            k: v for k, v in MARINE_BODY["current_units"].items() if k != "swell_wave_height"
        },
    }

    with pytest.raises(ValueError, match="missing units"):
        ingest(store, provider(marine=without_unit))

    assert client.get("/api/conditions/current").status_code == 503


def test_a_structurally_malformed_payload_is_rejected(store, client) -> None:
    with pytest.raises(ValueError, match="Unexpected Open-Meteo payload"):
        ingest(store, provider(marine={"current": {}}))

    assert client.get("/api/conditions/current").status_code == 503


def test_a_failed_run_leaves_earlier_conditions_intact(store, client) -> None:
    """The second source failing is the case that matters.

    Failing on the first fetch never exercises the ordering guarantee: conditions are
    written after both sources succeed, so only a mid-run failure can prove that a
    partial run leaves nothing behind. With the stub failing first, moving
    record_conditions between the two fetches left the whole suite green.
    """
    ingest(store, provider())

    def half_broken(request: httpx.Request) -> httpx.Response:
        if "marine" in request.url.host:
            return httpx.Response(200, json=MARINE_BODY)
        return httpx.Response(500, json={"error": "weather is down"})

    with pytest.raises(httpx.HTTPStatusError):
        ingest(store, httpx.MockTransport(half_broken))

    body = client.get("/api/conditions/current").json()
    assert body["swell_height"]["value"] == 8.1
    assert body["observed_at"] == "2026-02-13T09:00"


# --- retry policy -------------------------------------------------------------


def test_a_client_error_is_not_retried(store) -> None:
    """A 400 is the provider saying we are wrong. Asking again cannot change that.

    This regressed once: catching httpx.HTTPError around raise_for_status swallowed
    HTTPStatusError and retried 400s and 404s three times each.
    """
    transport, seen = failing_provider(400)

    with pytest.raises(httpx.HTTPStatusError):
        ingest(store, transport)

    assert len(seen) == 1


def test_a_server_error_is_retried_the_full_number_of_attempts(store) -> None:
    transport, seen = failing_provider(500)

    with pytest.raises(httpx.HTTPStatusError):
        ingest(store, transport)

    assert len(seen) == 3


def test_a_connection_failure_is_retried_and_backs_off(store) -> None:
    """The transport-failure path had no test at all: deleting its backoff left the
    whole suite green."""
    transport, seen = unreachable_provider()
    waits: list[float] = []

    with pytest.raises(httpx.ConnectError):
        ingest(store, transport, sleep=waits.append)

    assert len(seen) == 3
    assert waits == sorted(waits)
    assert all(wait > 0 for wait in waits), f"expected backoff, got {waits}"


def test_a_rate_limit_is_retried_and_waits_as_instructed(store) -> None:
    """429 carries a Retry-After we are obliged to honour rather than guess at."""
    transport, seen = failing_provider(429, {"Retry-After": "7"})
    waits: list[float] = []

    with pytest.raises(httpx.HTTPStatusError):
        ingest(store, transport, sleep=waits.append)

    assert len(seen) == 3
    assert 7 in waits, f"expected to honour Retry-After: 7, waited {waits}"


def test_a_quota_error_dressed_as_a_client_error_is_still_retried(store) -> None:
    """Open-Meteo has signalled quota exhaustion with a 4xx carrying a reason string.
    Treating that as permanent would turn a wait-and-retry into a hard failure."""
    quota = {"error": True, "reason": "Daily API request limit exceeded"}
    transport, seen = failing_provider(400, body=quota)

    with pytest.raises(httpx.HTTPStatusError):
        ingest(store, transport)

    assert len(seen) == 3


@pytest.mark.parametrize(
    "header",
    ["inf", "1e400", "-5", "nan", "not-a-number", "Wed, 21 Oct 2026 07:28:00 GMT"],
)
def test_a_hostile_retry_after_cannot_stall_the_run(store, header) -> None:
    """Retry-After is provider-controlled input. 'inf' previously hung the run forever;
    negatives and NaN raised out of time.sleep."""
    transport, _ = failing_provider(429, {"Retry-After": header})
    waits: list[float] = []

    with pytest.raises(httpx.HTTPStatusError):
        ingest(store, transport, sleep=waits.append)

    assert all(0 <= wait <= 60 for wait in waits), f"unbounded wait for {header!r}: {waits}"


# --- configuration ------------------------------------------------------------


def test_a_missing_database_is_a_fault_not_an_absence_of_data(tmp_path) -> None:
    """Opening the serving store must not create it. A read-only API that creates an
    empty database turns a misconfigured path into a confident 'no conditions yet'."""
    with pytest.raises(StoreUnavailable):
        Store(tmp_path / "nowhere" / "missing.db", create=False)

    assert not (tmp_path / "nowhere").exists()


def test_the_default_store_does_not_depend_on_the_working_directory(tmp_path) -> None:
    """Ingesting from one directory and serving from another silently used two different
    databases, and the API answered 503 while holding data.

    Asserting the path is merely absolute does not catch that: Path("data/x.db").resolve()
    is absolute too, and cwd-dependent. This resolves it from two directories instead.
    """
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        from_temp = (
            Store(create=False, writable=False).path
            if DEFAULT_DATABASE.exists()
            else DEFAULT_DATABASE
        )
        os.chdir(original)
        from_repo = DEFAULT_DATABASE
    finally:
        os.chdir(original)

    assert from_temp == from_repo
    assert DEFAULT_DATABASE.is_absolute()


def test_every_ingested_reading_is_served_by_the_api() -> None:
    """A reading can be fetched and stored yet never reach the user.

    Deriving the requested variables from the reading map closed only the fetch side.
    A new reading name over a variable already requested passed all 24 tests, was
    ingested, was written to the store, and was then silently dropped by the response
    model — pydantic ignores extra fields by default. This pins the two together.
    """
    ingested = set(MARINE_READINGS) | set(WEATHER_READINGS)
    served = {name for name in CurrentConditions.model_fields if name not in METADATA_FIELDS}

    assert ingested == served, (
        f"ingested but never served: {sorted(ingested - served)}; "
        f"served but never ingested: {sorted(served - ingested)}"
    )


def test_the_serving_store_cannot_write(store, tmp_path) -> None:
    """ADR 0005 says the API is strictly a reader. Enforced by SQLite, not convention:
    `create=False` alone still opened a read-write connection."""
    ingest(store, provider())
    reader = Store(store.path, create=False)

    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        reader.record_conditions("2026-02-13T09:00", 0.0, 0.0, {})

    reader.close()


def test_a_misconfigured_database_path_explains_itself(tmp_path, monkeypatch) -> None:
    """A missing database is a configuration fault, and must not read as missing data.

    The handler for this previously sat inside the endpoint body, where it could never
    fire — dependencies resolve first — so the API returned a bare 500 with no detail.
    """
    from nazarenow.api import app, default_store

    default_store.cache_clear()
    monkeypatch.setenv("NAZARENOW_DB", str(tmp_path / "nowhere.db"))
    app.dependency_overrides.clear()

    try:
        response = TestClient(app, raise_server_exceptions=False).get("/api/conditions/current")
        assert response.status_code == 500
        assert "store unavailable" in response.json()["detail"].lower()
    finally:
        default_store.cache_clear()
