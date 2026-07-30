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
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import ingest
from nazarenow.api import CurrentConditions, Reading
from nazarenow.sources.open_meteo import (
    MARINE_READINGS,
    MAX_BACKOFF_SECONDS,
    WEATHER_READINGS,
)
from nazarenow.store import DEFAULT_DATABASE, Store, StoreUnavailable

DAY_HOURS = [f"2026-02-13T{hour:02d}:00" for hour in range(24)]

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
    # The provider returns the forecast range in the same response as the current
    # conditions, so a realistic fixture carries both. A full day, because a Pipeline
    # Run rejects anything shorter as a degraded response. The forecast itself is
    # exercised in test_forecast.py.
    "hourly_units": {
        "time": "iso8601",
        "wave_height": "m",
        "wave_direction": "°",
        "wave_period": "s",
        "swell_wave_height": "m",
        "swell_wave_direction": "°",
        "swell_wave_period": "s",
        "sea_surface_temperature": "°C",
    },
    "hourly": {
        "time": DAY_HOURS,
        "wave_height": [8.4] * 24,
        "wave_direction": [295] * 24,
        "wave_period": [16.2] * 24,
        "swell_wave_height": [8.1] * 24,
        "swell_wave_direction": [298] * 24,
        "swell_wave_period": [17.0] * 24,
        "sea_surface_temperature": [15.2] * 24,
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
    "hourly_units": {
        "time": "iso8601",
        "temperature_2m": "°C",
        "wind_speed_10m": "km/h",
        "wind_direction_10m": "°",
    },
    "hourly": {
        "time": DAY_HOURS,
        "temperature_2m": [13.4] * 24,
        "wind_speed_10m": [11.0] * 24,
        "wind_direction_10m": [115] * 24,
    },
}


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
    # "1000000" is the case the cap exists for: finite, valid, and far too long to wait.
    # Without it the clamp was never the operative branch, and deleting the clamp
    # entirely left the whole suite green.
    ["inf", "1e400", "-5", "nan", "not-a-number", "Wed, 21 Oct 2026 07:28:00 GMT", "1000000"],
)
def test_a_hostile_retry_after_cannot_stall_the_run(store, header) -> None:
    """Retry-After is provider-controlled input. 'inf' previously hung the run forever;
    negatives and NaN raised out of time.sleep."""
    transport, _ = failing_provider(429, {"Retry-After": header})
    waits: list[float] = []

    with pytest.raises(httpx.HTTPStatusError):
        ingest(store, transport, sleep=waits.append)

    assert all(0 <= wait <= MAX_BACKOFF_SECONDS for wait in waits), (
        f"unbounded wait for {header!r}: {waits}"
    )


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

    The module constant is bound at import, so chdir-then-compare asserts that a value
    equals itself — which is how two earlier versions of this test passed while the bug
    was present. The path has to be derived by a fresh import from a different working
    directory, and that has to happen in a separate process: reloading the module in
    this one rebinds StoreUnavailable to a new class object, which the API's except
    clause and exception handler no longer recognise, breaking unrelated tests.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from nazarenow.store import DEFAULT_DATABASE; print(DEFAULT_DATABASE)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    from_elsewhere = Path(result.stdout.strip())

    # Two assertions because the property has two failure modes, and each earlier
    # version of this test caught only one of them. A relative path is cwd-dependent and
    # compares equal to itself across processes, so the subprocess check alone misses it;
    # a path built from Path.cwd() is absolute, so is_absolute() alone misses that. This
    # test has now been wrong three times for want of keeping both.
    assert DEFAULT_DATABASE.is_absolute(), f"{DEFAULT_DATABASE} is relative, so it moves"
    assert from_elsewhere == DEFAULT_DATABASE, (
        f"the default database moved with the working directory: "
        f"{from_elsewhere} != {DEFAULT_DATABASE}"
    )


def test_every_ingested_reading_is_served_by_the_api() -> None:
    """A reading can be fetched and stored yet never reach the user.

    Deriving the requested variables from the reading map closed only the fetch side.
    A new reading name over a variable already requested passed all 24 tests, was
    ingested, was written to the store, and was then silently dropped by the response
    model — pydantic ignores extra fields by default. This pins the two together.
    """
    ingested = set(MARINE_READINGS) | set(WEATHER_READINGS)
    # Derived from the annotation, not a hardcoded list of the fields that are not
    # readings — such a list is one more thing to forget to update.
    served = {
        name
        for name, field in CurrentConditions.model_fields.items()
        if field.annotation is Reading
    }

    assert ingested == served, (
        f"ingested but never served: {sorted(ingested - served)}; "
        f"served but never ingested: {sorted(served - ingested)}"
    )


def test_the_serving_store_cannot_write(store) -> None:
    """ADR 0005 says the API is strictly a reader. Enforced by SQLite, not convention:
    `create=False` alone still opened a read-write connection."""
    ingest(store, provider())
    reader = Store(store.path, create=False)
    try:
        # record_run, not record_conditions: production writes through record_run, and
        # a read-only guard on a method nothing calls guards nothing.
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.record_run("2026-02-13T09:00", 0.0, 0.0, {}, [], [])
    finally:
        reader.close()


@pytest.mark.parametrize("kind", ["directory", "not-a-database", "empty"])
def test_every_kind_of_broken_database_path_is_rejected_at_startup(tmp_path, kind) -> None:
    """Only a missing file was ever checked eagerly. A directory, a file that is not a
    database, and a zero-byte file all opened fine and failed later, inside the endpoint,
    where nothing handled them — the browser got a bare 500 with no CORS header."""
    targets = {
        "directory": tmp_path,
        "not-a-database": tmp_path / "notes.txt",
        "empty": tmp_path / "empty.db",
    }
    (tmp_path / "notes.txt").write_text("this is not a database")
    (tmp_path / "empty.db").touch()

    with pytest.raises(StoreUnavailable):
        Store(targets[kind], create=False)


def test_a_database_with_the_right_tables_but_wrong_columns_is_rejected(tmp_path) -> None:
    """Checking table names alone let a mangled schema through.

    Construction succeeded, then the first query failed inside the endpoint with "no
    such column" — an unhandled exception, which surfaces outside CORSMiddleware, so the
    browser saw an opaque CORS failure instead of a 500 it could read. Verifying by
    running the store's own queries catches the columns as well as the tables.
    """
    target = tmp_path / "mangled.db"
    connection = sqlite3.connect(target)
    connection.executescript(
        "CREATE TABLE raw_response (id INTEGER PRIMARY KEY, nonsense TEXT);"
        "CREATE TABLE offshore_conditions (id INTEGER PRIMARY KEY, nonsense TEXT);"
    )
    connection.commit()
    connection.close()

    with pytest.raises(StoreUnavailable, match="Cannot read"):
        Store(target, create=False)


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


def test_a_path_containing_uri_syntax_still_opens_read_only(tmp_path) -> None:
    """The database path is embedded in a SQLite URI and must be escaped.

    Unescaped, a '#' in any directory name starts a URI fragment: SQLite reads a
    truncated path, discards ?mode=ro, and creates a read-write database somewhere else
    entirely. Read-only mode and the never-create rule both fail, silently, and the
    reader then serves an empty database it just made.
    """
    awkward = tmp_path / "my#notes and things"
    awkward.mkdir()
    target = awkward / "nazarenow.db"

    writer = Store(target)
    writer.record_run("2026-02-13T09:00", 39.5, -9.2, {}, [], [])
    writer.close()

    reader = Store(target, create=False)
    try:
        assert reader.latest_conditions() is not None, "read a different database"
    finally:
        reader.close()

    assert sorted(p.name for p in awkward.iterdir()) == ["nazarenow.db"], "a stray file was created"
