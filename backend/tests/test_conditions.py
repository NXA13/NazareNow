"""Ingestion through to the API, driven at the agreed backend seam.

A test stubs the third-party providers at the HTTP boundary, executes a Pipeline Run,
then reads the result back through the API. Ingestion, validation and the store are all
internal to this seam and may be restructured freely.

Per ADR 0005 the request path must never contact a provider. conftest.py blocks outbound
sockets, so a test that reads the API without first running the pipeline would fail
loudly rather than quietly reaching the network.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from nazarenow.api import app, get_store
from nazarenow.pipeline import run_pipeline
from nazarenow.store import Store

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
    """Backoff is real behaviour, but waiting for it makes the suite slow enough
    that people stop running it. Injected so the retry path is exercised at speed."""


def provider(marine=MARINE_BODY, weather=WEATHER_BODY, status=200):
    """An httpx transport standing in for both Open-Meteo endpoints."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = marine if "marine" in request.url.host else weather
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "test.db")


@pytest.fixture
def client(store: Store) -> TestClient:
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_current_conditions_come_from_the_stored_pipeline_run(store, client) -> None:
    with httpx.Client(transport=provider()) as http:
        run_pipeline(store, http, sleep=no_sleep)

    body = client.get("/api/conditions/current").json()

    assert body["swell_height"]["value"] == 8.1
    assert body["swell_height"]["unit"] == "m"
    assert body["swell_period"]["value"] == 17.0
    assert body["swell_direction"]["value"] == 298
    assert body["wind_speed"]["value"] == 11.0
    assert body["wind_direction"]["value"] == 115
    assert body["air_temperature"]["value"] == 13.4
    assert body["water_temperature"]["value"] == 15.2


def test_the_api_reports_when_the_data_was_observed_and_fetched(store, client) -> None:
    with httpx.Client(transport=provider()) as http:
        run_pipeline(store, http, sleep=no_sleep)

    body = client.get("/api/conditions/current").json()

    assert body["observed_at"].startswith("2026-02-13T09:00")
    assert body["fetched_at"]
    assert body["placeholder"] is False


def test_no_conditions_yet_is_reported_rather_than_faked(client) -> None:
    """An empty store must not produce plausible-looking zeros."""
    response = client.get("/api/conditions/current")

    assert response.status_code == 503
    assert "no conditions" in response.json()["detail"].lower()


def test_raw_provider_responses_are_retained(store) -> None:
    with httpx.Client(transport=provider()) as http:
        run_pipeline(store, http, sleep=no_sleep)

    raw = store.raw_responses()

    assert {entry["source"] for entry in raw} == {"open-meteo-marine", "open-meteo-weather"}
    assert all(entry["body"] for entry in raw)


def test_a_malformed_payload_is_rejected_rather_than_stored(store, client) -> None:
    """A provider changing shape must fail the run, not poison the store."""
    broken = {"current_units": {}, "current": {"time": "2026-02-13T09:00"}}

    with httpx.Client(transport=provider(marine=broken)) as http, pytest.raises(ValueError):
        run_pipeline(store, http, sleep=no_sleep)

    assert client.get("/api/conditions/current").status_code == 503


def test_a_failed_run_leaves_earlier_conditions_intact(store, client) -> None:
    with httpx.Client(transport=provider()) as http:
        run_pipeline(store, http, sleep=no_sleep)

    with httpx.Client(transport=provider(status=500)) as http, pytest.raises(httpx.HTTPError):
        run_pipeline(store, http, sleep=no_sleep)

    body = client.get("/api/conditions/current").json()
    assert body["swell_height"]["value"] == 8.1
