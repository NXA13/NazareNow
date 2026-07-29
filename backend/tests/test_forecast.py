"""The forecast range, driven at the agreed backend seam.

Same seam as test_conditions.py: providers stubbed at the HTTP boundary, a Pipeline Run
executed, the result read back through the API.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest

from nazarenow.api import ForecastHour, Reading
from nazarenow.pipeline import run_pipeline
from nazarenow.sources.open_meteo import (
    MARINE_READINGS,
    WEATHER_READINGS,
)
from test_conditions import MARINE_BODY, WEATHER_BODY, ingest

# Three days of hourly data is enough to prove grouping, ordering and summarising
# without a fixture nobody can read. The provider returns sixteen.
HOURS = [f"2026-02-{day:02d}T{hour:02d}:00" for day in (12, 13, 14) for hour in range(24)]


# For the peak day, height, period and direction each peak at a *different* hour, and
# none of those is hour zero or the last hour. Every degenerate fixture this project has
# shipped failed for want of exactly that: monotonic height made the peak hour the last
# hour, and constant direction gave direction no argmax at all, so a summary reading the
# wrong hour was indistinguishable from a correct one.
PEAK_DAY = "2026-02-13"
HEIGHT_PEAK_HOUR = 8
PERIOD_PEAK_HOUR = 15
DIRECTION_PEAK_HOUR = 20


def marine_with_hourly() -> dict:
    """A swell building through the 13th and easing on the 14th."""
    heights, periods, directions = [], [], []
    for stamp in HOURS:
        day, hour = stamp[8:10], int(stamp[11:13])
        if day == "13":
            heights.append(8.5 if hour == HEIGHT_PEAK_HOUR else 7.0)
            periods.append(
                23.0 if hour == PERIOD_PEAK_HOUR else 19.0 if hour == HEIGHT_PEAK_HOUR else 17.0
            )
            directions.append(
                350 if hour == DIRECTION_PEAK_HOUR else 270 if hour == HEIGHT_PEAK_HOUR else 298
            )
        else:
            base = {"12": 1.4, "14": 3.5}[day]
            heights.append(round(base + (0.2 if hour == 6 else 0.0), 2))
            periods.append({"12": 9.0, "14": 12.0}[day] + (1.0 if hour == 11 else 0.0))
            directions.append({"12": 250, "14": 280}[day] + (5 if hour == 17 else 0))

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
            # Combined Sea carries its own values. Assigning the same list objects as
            # Swell meant a summary reading the wrong family returned identical numbers,
            # so nothing could tell them apart — the one distinction CLAUDE.md calls
            # load-bearing.
            "wave_height": [round(h + 0.3, 2) for h in heights],
            # Not a monotonic shift of the swell period: adding a constant preserves the
            # argmax, so `longest` computed over the wrong family picked the same hour
            # and returned the same value. Combined Sea peaks at its own hour.
            "wave_period": [
                round(p + (9.0 if h % 24 == 3 else 1.7), 2) for h, p in enumerate(periods)
            ],
            "wave_direction": [(d + 31) % 360 for d in directions],
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

    # Height peaks at 08:00, period at 15:00, direction at 20:00. Hour zero holds a
    # fourth set of values. Any summary reading the wrong hour reports a wrong number.
    assert peak["peak_swell_height"] == {"value": 8.5, "unit": "m"}
    assert peak["swell_period_at_peak"] == {"value": 19.0, "unit": "s"}
    assert peak["swell_direction_at_peak"] == {"value": 270, "unit": "°"}
    assert peak["longest_swell_period"] == {"value": 23.0, "unit": "s"}


def test_a_day_carries_its_hours_in_order(store, client) -> None:
    ingest(store, forecasting_provider())

    body = client.get("/api/conditions/forecast").json()
    day = next(day for day in body["days"] if day["date"] == "2026-02-13")

    assert len(day["hours"]) == 24
    assert [hour["at"] for hour in day["hours"]] == sorted(hour["at"] for hour in day["hours"])
    assert day["hours"][0]["at"] == "2026-02-13T00:00"
    assert day["hours"][0]["swell_height"] == {"value": 7.0, "unit": "m"}
    assert day["hours"][HEIGHT_PEAK_HOUR]["swell_height"] == {"value": 8.5, "unit": "m"}
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


def test_a_response_with_barely_any_usable_hours_keeps_the_previous_forecast(store, client) -> None:
    """Zero was not the only destructive case. A response nulling all but one hour
    replaced seventy-two stored hours with one, silently and with exit code zero."""
    ingest(store, forecasting_provider())
    before = client.get("/api/conditions/forecast").json()

    nearly_dead = marine_with_hourly()
    for name in nearly_dead["hourly"]:
        if name != "time":
            nearly_dead["hourly"][name] = [nearly_dead["hourly"][name][0]] + [None] * (
                len(nearly_dead["hourly"]["time"]) - 1
            )

    with pytest.raises(ValueError, match="fewer than"):
        ingest(store, forecasting_provider(marine=nearly_dead))

    assert client.get("/api/conditions/forecast").json() == before


def test_a_rejected_forecast_does_not_advance_the_current_conditions(store, client) -> None:
    """The run is all-or-nothing. Writing conditions before checking the forecast left
    the store half-updated, which this pipeline's docstring promises never happens."""
    ingest(store, forecasting_provider())
    before = client.get("/api/conditions/current").json()

    dead = marine_with_hourly()
    for name in dead["hourly"]:
        if name != "time":
            dead["hourly"][name] = [None] * len(dead["hourly"]["time"])

    with pytest.raises(ValueError):
        ingest(store, forecasting_provider(marine=dead))

    assert client.get("/api/conditions/current").json() == before


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

    with pytest.raises(ValueError, match="usable forecast hours"):
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
        # The literal the ticket asks for, not the constant the code uses. Comparing
        # against FORECAST_DAYS was self-referential: changing it to 7 — the exact
        # regression this test names — passed.
        assert url.params.get("forecast_days") == "16"
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


def test_the_fixture_can_tell_the_summary_apart_from_a_wrong_hour() -> None:
    """A test on the fixture, because the fixture is what kept failing.

    Three separate attempts at the summary guard passed against a summary reading the
    wrong hour, every time because the fixture was degenerate in some dimension nobody
    had looked at. This asserts the property those attempts assumed: on the peak day,
    height, period and direction each peak at a distinct hour, and none of them is hour
    zero or the last hour. If that stops being true, this fails rather than quietly
    hollowing out every assertion downstream.
    """
    hourly = marine_with_hourly()["hourly"]
    peak_day = [i for i, stamp in enumerate(hourly["time"]) if stamp.startswith(PEAK_DAY)]

    def argmax(variable: str) -> int:
        values = [hourly[variable][i] for i in peak_day]
        return values.index(max(values))

    hours = {
        "height": argmax("swell_wave_height"),
        "period": argmax("swell_wave_period"),
        "direction": argmax("swell_wave_direction"),
    }

    assert len(set(hours.values())) == 3, f"two quantities peak at the same hour: {hours}"
    assert 0 not in hours.values(), f"a quantity peaks at hour zero: {hours}"
    assert 23 not in hours.values(), f"a quantity peaks at the last hour: {hours}"

    # Distinct argmax hours are only a proxy. `summarise` reads period and direction at
    # the *peak-height* hour, so what actually has to hold is that the value it reads
    # there appears nowhere else in the day — otherwise reading some other hour returns
    # the same number and no assertion can tell. Collapsing the period at hour 8 to the
    # day's baseline satisfies the argmax check while hollowing out the summary tests.
    for swell_variable, sea_variable in (
        ("swell_wave_period", "wave_period"),
        ("swell_wave_direction", "wave_direction"),
        ("swell_wave_height", "wave_height"),
    ):
        swell = [hourly[swell_variable][i] for i in peak_day]
        sea = [hourly[sea_variable][i] for i in peak_day]
        assert swell != sea, (
            f"{swell_variable} and {sea_variable} hold the same values, so a summary "
            f"reading Combined Sea where it should read Swell is undetectable"
        )

    read_hour = hours["height"]
    for variable in ("swell_wave_period", "swell_wave_direction"):
        values = [hourly[variable][i] for i in peak_day]
        assert values.count(values[read_hour]) == 1, (
            f"{variable} at the hour summarise reads ({read_hour}:00) is not unique in "
            f"the day, so reading the wrong hour would be undetectable"
        )


def test_a_failure_partway_through_a_write_leaves_nothing_changed(store, client) -> None:
    """Conditions and forecast are written in one transaction, or not at all.

    They used to be two commits, so a fault between them advanced the current conditions
    while the forecast stayed behind — the half-updated picture the pipeline's docstring
    promises never happens. Moving validation earlier did not fix that; only sharing a
    transaction does. A repeated timestamp makes SQLite reject the second insert, which
    must roll back the first.
    """
    ingest(store, forecasting_provider())
    conditions_before = client.get("/api/conditions/current").json()
    forecast_before = client.get("/api/conditions/forecast").json()

    hour = forecast_before["days"][0]["hours"][0]

    # (a) The forecast write fails. The conditions written alongside it must roll back.
    duplicated = [
        {"at": "2026-03-01T00:00", "readings": hour},
        {"at": "2026-03-01T00:00", "readings": hour},
    ]
    with pytest.raises(sqlite3.IntegrityError):
        store.record_run("2026-03-01T00:00", 1.0, 2.0, {"nonsense": {}}, duplicated)

    assert client.get("/api/conditions/current").json() == conditions_before
    assert client.get("/api/conditions/forecast").json() == forecast_before

    # (b) The conditions write fails. The forecast must be untouched — including the
    # DELETE. Testing only (a) pinned write *ordering*, not one transaction: an
    # implementation committing the conditions last also passed it.
    with pytest.raises(sqlite3.IntegrityError):
        store.record_run(
            None, 1.0, 2.0, {"nonsense": {}}, [{"at": "2026-03-02T00:00", "readings": hour}]
        )  # type: ignore[arg-type]

    assert client.get("/api/conditions/current").json() == conditions_before
    assert client.get("/api/conditions/forecast").json() == forecast_before
