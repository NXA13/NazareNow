"""The forecast range, driven at the agreed backend seam.

Same seam as test_conditions.py: providers stubbed at the HTTP boundary, a Pipeline Run
executed, the result read back through the API.
"""

from __future__ import annotations

import httpx
import pytest

from nazarenow.api import ForecastHour, Reading
from nazarenow.pipeline import run_pipeline
from nazarenow.sources.open_meteo import (
    FORECAST_DAYS,
    MARINE_READINGS,
    WEATHER_READINGS,
)
from test_conditions import MARINE_BODY, WEATHER_BODY, ingest

# Three days of hourly data is enough to prove grouping, ordering and summarising
# without a fixture nobody can read. The provider returns sixteen.
HOURS = [f"2026-02-{day:02d}T{hour:02d}:00" for day in (12, 13, 14) for hour in range(24)]


def marine_with_hourly() -> dict:
    """A swell building through the 13th and easing on the 14th."""
    heights, periods, directions = [], [], []
    for index, stamp in enumerate(HOURS):
        day = stamp[8:10]
        base = {"12": 2.0, "13": 7.0, "14": 3.5}[day]
        heights.append(round(base + (index % 24) * 0.05, 2))
        # Period varies across the day, and its maximum deliberately falls at a
        # different hour from the peak height. A constant period made the summary
        # assertion vacuous: it passed against a mutant reading hours[0].
        # Period rises through the day *and* spikes at 15:00, so three hours give three
        # different values: hour 0, the peak-height hour (23:00), and the longest-period
        # hour. A fixture where any two of those agree cannot tell a correct summary
        # from one reading the wrong hour — which is how the earlier version passed
        # against a mutant sourcing hours[0].
        base = {"12": 9.0, "13": 17.0, "14": 12.0}[day]
        hour = index % 24
        periods.append(round(base + hour * 0.1 + (5.0 if hour == 15 else 0.0), 2))
        directions.append({"12": 250, "13": 298, "14": 280}[day])

    return {
        **MARINE_BODY,
        "hourly_units": {
            "time": "iso8601",
            "swell_wave_height": "m",
            "swell_wave_period": "s",
            "swell_wave_direction": "°",
            "wave_height": "m",
            "wave_period": "s",
            "wave_direction": "°",
            "sea_surface_temperature": "°C",
        },
        "hourly": {
            "time": HOURS,
            "swell_wave_height": heights,
            "swell_wave_period": periods,
            "swell_wave_direction": directions,
            "wave_height": [h + 0.3 for h in heights],
            "wave_period": periods,
            "wave_direction": directions,
            "sea_surface_temperature": [15.0] * len(HOURS),
        },
    }


def weather_with_hourly() -> dict:
    return {
        **WEATHER_BODY,
        "hourly_units": {
            "time": "iso8601",
            "temperature_2m": "°C",
            "wind_speed_10m": "km/h",
            "wind_direction_10m": "°",
        },
        "hourly": {
            "time": HOURS,
            "temperature_2m": [13.0] * len(HOURS),
            "wind_speed_10m": [10.0] * len(HOURS),
            "wind_direction_10m": [115] * len(HOURS),
        },
    }


def forecasting_provider(marine=None, weather=None):
    marine = marine or marine_with_hourly()
    weather = weather or weather_with_hourly()

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=marine if "marine" in request.url.host else weather)

    return httpx.MockTransport(handle)


def test_the_forecast_covers_every_day_the_provider_returned(store, client) -> None:
    ingest(store, forecasting_provider())

    body = client.get("/api/conditions/forecast").json()

    assert [day["date"] for day in body["days"]] == ["2026-02-12", "2026-02-13", "2026-02-14"]


def test_a_quiet_day_is_present_rather_than_omitted(store, client) -> None:
    """Absence would read as missing data. The 12th is small and must still appear."""
    ingest(store, forecasting_provider())

    body = client.get("/api/conditions/forecast").json()
    quiet = next(day for day in body["days"] if day["date"] == "2026-02-12")

    assert quiet["peak_swell_height"]["value"] < 4
    assert quiet["hours"], "a quiet day still has hourly detail"


def test_each_day_summarises_swell_without_collapsing_it(store, client) -> None:
    """Height, period and direction stay distinguishable — a single size figure hides
    the difference between a big messy sea and a groundswell worth flying for."""
    ingest(store, forecasting_provider())

    body = client.get("/api/conditions/forecast").json()
    peak = next(day for day in body["days"] if day["date"] == "2026-02-13")

    assert peak["peak_swell_height"] == {"value": 8.15, "unit": "m"}
    # The height peaks at 23:00 and the period at 15:00, so a summary that read both
    # from the same hour would get one of them wrong.
    # 19.3 at the peak-height hour (23:00), 23.5 at the longest-period hour (15:00),
    # and 17.0 at hour zero — all different, so any confusion between them shows.
    assert peak["swell_period_at_peak"] == {"value": 19.3, "unit": "s"}
    assert peak["swell_direction_at_peak"] == {"value": 298, "unit": "°"}
    assert peak["longest_swell_period"] == {"value": 23.5, "unit": "s"}


def test_a_day_carries_its_hours_in_order(store, client) -> None:
    ingest(store, forecasting_provider())

    body = client.get("/api/conditions/forecast").json()
    day = next(day for day in body["days"] if day["date"] == "2026-02-13")

    assert len(day["hours"]) == 24
    assert [hour["at"] for hour in day["hours"]] == sorted(hour["at"] for hour in day["hours"])
    assert day["hours"][0]["at"] == "2026-02-13T00:00"
    assert day["hours"][0]["swell_height"] == {"value": 7.0, "unit": "m"}
    assert day["hours"][0]["wind_speed"] == {"value": 10.0, "unit": "km/h"}


def test_the_forecast_reports_when_it_was_fetched(store, client) -> None:
    ingest(store, forecasting_provider())

    body = client.get("/api/conditions/forecast").json()

    assert body["fetched_at"]


def test_no_forecast_yet_is_reported_rather_than_faked(client) -> None:
    response = client.get("/api/conditions/forecast")

    assert response.status_code == 503


def test_a_later_run_replaces_the_previous_forecast(store, client) -> None:
    """Forecasts are superseded, not accumulated: two runs must not double the days."""
    ingest(store, forecasting_provider())
    ingest(store, forecasting_provider())

    body = client.get("/api/conditions/forecast").json()

    assert len(body["days"]) == 3


def test_hourly_data_missing_a_variable_is_rejected(store, client) -> None:
    broken = marine_with_hourly()
    del broken["hourly"]["swell_wave_period"]

    with pytest.raises(ValueError, match="hourly"):
        ingest(store, forecasting_provider(marine=broken))

    assert client.get("/api/conditions/forecast").status_code == 503


def test_hourly_arrays_of_unequal_length_are_rejected(store, client) -> None:
    """A short array would silently truncate the forecast, or misalign every reading
    against the wrong hour — which looks like data rather than like a fault."""
    broken = marine_with_hourly()
    broken["hourly"]["swell_wave_height"] = broken["hourly"]["swell_wave_height"][:10]

    with pytest.raises(ValueError, match="length"):
        ingest(store, forecasting_provider(marine=broken))

    assert client.get("/api/conditions/forecast").status_code == 503


def test_current_conditions_still_work_alongside_the_forecast(store, client) -> None:
    ingest(store, forecasting_provider())

    assert client.get("/api/conditions/current").status_code == 200


def test_the_pipeline_still_takes_one_request_per_provider(store) -> None:
    """Current and hourly arrive in the same response, so adding the forecast must not
    double the load on a free API."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        marine = "marine" in request.url.host
        return httpx.Response(200, json=marine_with_hourly() if marine else weather_with_hourly())

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        run_pipeline(store, http, sleep=lambda _: None)

    assert len(seen) == 2


def test_hours_the_provider_could_not_model_are_dropped(store, client) -> None:
    """Open-Meteo pads its time axis to the requested range and nulls the hours it has
    no data for — marine readings stop around nine days while the axis runs to sixteen.

    Those hours must not reach the store. A null has no honest rendering, and coercing
    it to zero would draw a flat calm sea for the back half of every forecast.
    """
    padded = marine_with_hourly()
    for name in ("swell_wave_height", "swell_wave_period", "swell_wave_direction"):
        padded["hourly"][name] = padded["hourly"][name][:48] + [None] * 24

    ingest(store, forecasting_provider(marine=padded))

    body = client.get("/api/conditions/forecast").json()

    assert [day["date"] for day in body["days"]] == ["2026-02-12", "2026-02-13"]
    assert all(day["hours"] for day in body["days"])


def test_a_response_with_no_usable_hours_keeps_the_previous_forecast(store, client) -> None:
    """An all-null response parses cleanly, yields nothing, and used to delete the lot.

    Verified before the fix: seventy-two good hours became zero, the run exited without
    error, and the page then said no pipeline run had stored a forecast — blaming
    absence for a successful-looking run that had just destroyed nine real days.
    """
    ingest(store, forecasting_provider())
    assert len(client.get("/api/conditions/forecast").json()["days"]) == 3

    dead = marine_with_hourly()
    for name in dead["hourly"]:
        if name != "time":
            dead["hourly"][name] = [None] * len(dead["hourly"]["time"])

    with pytest.raises(ValueError, match="no usable forecast hours"):
        ingest(store, forecasting_provider(marine=dead))

    assert len(client.get("/api/conditions/forecast").json()["days"]) == 3


def test_a_duplicated_hour_is_rejected(store, client) -> None:
    """A repeated timestamp silently drops an hour and hands its reading to another."""
    duplicated = marine_with_hourly()
    axis = duplicated["hourly"]["time"]
    duplicated["hourly"]["time"] = [axis[0], axis[0], *axis[2:]]

    with pytest.raises(ValueError, match="duplicate timestamps"):
        ingest(store, forecasting_provider(marine=duplicated))


def test_the_provider_is_asked_for_the_whole_range_hour_by_hour(store) -> None:
    """Nothing pinned the request itself: dropping forecast_days left the suite green
    while the provider quietly fell back to its seven-day default."""
    asked: list[httpx.URL] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url)
        marine = "marine" in request.url.host
        return httpx.Response(200, json=marine_with_hourly() if marine else weather_with_hourly())

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        run_pipeline(store, http, sleep=lambda _: None)

    for url in asked:
        assert url.params.get("forecast_days") == str(FORECAST_DAYS)
        assert url.params.get("hourly"), "the hourly block must be requested"
        assert url.params.get("current"), "current conditions must still be requested"


def test_every_ingested_hourly_reading_is_served_by_the_api() -> None:
    """The same guard the current-conditions endpoint has. Without it, dropping two
    fields from ForecastHour left the whole suite green while the readings were
    ingested, stored, and silently discarded on the way out."""
    ingested = set(MARINE_READINGS) | set(WEATHER_READINGS)
    served = {
        name for name, field in ForecastHour.model_fields.items() if field.annotation is Reading
    }

    assert ingested == served, (
        f"ingested but never served: {sorted(ingested - served)}; "
        f"served but never ingested: {sorted(served - ingested)}"
    )
