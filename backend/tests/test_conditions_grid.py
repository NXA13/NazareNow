"""The grid of conditions the map is drawn from (#120).

Twenty-five points over exactly the frame the map draws, fetched in one request per API and
held to the same standard as the single offshore point: a missing reading, a null one, or one
in an unexpected unit fails the grid rather than reaching the store.

**The failure these tests are really about is the quiet one.** A dropped reading does not look
like a fault on a wind field — it looks like calm weather, which is the most dangerous thing
this map could say. So the validation cases outnumber the happy path here on purpose.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from helpers import forecast_provider, ingest, is_grid_request
from nazarenow.cycle import INTERVAL_SECONDS, STALE_AFTER_HOURS, STALE_AFTER_SECONDS
from nazarenow.pipeline import GRID_UNAVAILABLE, MINIMUM_FORECAST_HOURS
from nazarenow.runs import FailureKind
from nazarenow.sources.open_meteo import (
    GRID_EAST,
    GRID_NORTH,
    GRID_SIDE,
    GRID_SOUTH,
    GRID_WEST,
    MARINE_VARIABLES,
    TIMEZONE,
    fetch_grid,
    fetch_grid_marine,
    grid_points,
    validate_grid,
)

URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def point_body(variables: list[str] = MARINE_VARIABLES, **overrides: Any) -> dict[str, Any]:
    """One location's block, well-formed unless a test breaks it on purpose."""
    body = {
        "timezone": TIMEZONE,
        "current": {"time": "2026-02-13T09:00", **{name: 1.5 for name in variables}},
        "current_units": {
            "time": "iso8601",
            "swell_wave_height": "m",
            "swell_wave_period": "s",
            "swell_wave_direction": "°",
            "wave_height": "m",
            "wave_period": "s",
            "wave_direction": "°",
            "sea_surface_temperature": "°C",
        },
    }
    body.update(overrides)
    return body


def grid_body(count: int = GRID_SIDE * GRID_SIDE) -> list[dict[str, Any]]:
    return [point_body() for _ in range(count)]


def transport_for(payload: Any, status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handle)


def rewrite_grid(
    transport: httpx.MockTransport, change: Any, marine: bool = True, weather: bool = True
) -> httpx.MockTransport:
    """The same provider, with its grid responses passed through `change` on the way out.

    Wrapping rather than parametrising `forecast_provider`: the two cases below break the
    grid in ways no real provider option describes, and a fixture growing a knob per
    malformation ends up able to produce responses that could not happen.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        response = transport.handler(request)
        if not is_grid_request(request):
            return response
        if not (marine if "marine" in request.url.host else weather):
            return response
        return httpx.Response(200, json=change(json.loads(response.content)))

    return httpx.MockTransport(handle)


def weather_grid_observed_at(transport: httpx.MockTransport, at: str) -> httpx.MockTransport:
    """A provider whose weather grid reports its own observation time, apart from the marine one.

    Named for what it sets rather than for which of the two ends up older, so a test that
    moves the time across the marine grid's does not have to fight the helper's name.
    """

    def restamp(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**block, "current": {**block["current"], "time": at}} for block in blocks]

    return rewrite_grid(transport, restamp, marine=False)


def one_weather_point_observed_at(
    transport: httpx.MockTransport, index: int, at: str
) -> httpx.MockTransport:
    """A provider whose weather grid is current everywhere except at one location.

    Real enough to be worth pinning: the twenty-five coordinates are answered from whichever
    of the provider's own cells each fell in, and there is nothing promising those cells were
    all refreshed in the same pass.
    """

    def restamp(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        aged = [{**block, "current": dict(block["current"])} for block in blocks]
        aged[index]["current"]["time"] = at
        return aged

    return rewrite_grid(transport, restamp, marine=False)


def malformed_grid(transport: httpx.MockTransport) -> httpx.MockTransport:
    """A grid response that arrived and is not a grid: one object where an array was asked for.

    The shape Open-Meteo returns for a *single* coordinate, which is why this is the
    malformation worth pinning — it is the one a real contract change would most plausibly
    produce, and the one that would quietly become a wind field of a single dart.
    """
    return rewrite_grid(transport, lambda blocks: blocks[0])


def malformed_weather_grid(transport: httpx.MockTransport) -> httpx.MockTransport:
    """Only the *weather* grid comes back malformed; the marine one is fine."""
    return rewrite_grid(transport, lambda blocks: blocks[0], marine=False)


class TestTheGridCoversTheMap:
    def test_it_is_twenty_five_points(self):
        assert len(grid_points()) == GRID_SIDE * GRID_SIDE == 25

    def test_its_corners_are_the_frame_the_map_draws(self):
        # **The guarantee this grid exists to give**: a wind glyph placed from a grid point
        # can never sit outside the drawn map, because there is no grid point outside it.
        # Asserted against the frame's own numbers rather than against a copy of them.
        points = grid_points()

        assert points[0] == (GRID_NORTH, GRID_WEST)
        assert points[GRID_SIDE - 1] == (GRID_NORTH, GRID_EAST)
        assert points[-GRID_SIDE] == (GRID_SOUTH, GRID_WEST)
        assert points[-1] == (GRID_SOUTH, GRID_EAST)

    def test_no_point_falls_outside_the_frame(self):
        for latitude, longitude in grid_points():
            assert GRID_SOUTH <= latitude <= GRID_NORTH
            assert GRID_WEST <= longitude <= GRID_EAST

    def test_every_point_is_distinct(self):
        # A rounding step that collapsed two rows would leave the map with a hole and a
        # duplicate, and the store's key would hide it.
        assert len(set(grid_points())) == GRID_SIDE * GRID_SIDE


class TestOneRequestNotTwentyFive:
    def test_all_coordinates_go_in_a_single_request(self):
        seen: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=grid_body())

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            fetch_grid_marine(client)

        assert len(seen) == 1
        latitudes = seen[0].url.params["latitude"].split(",")
        assert len(latitudes) == 25

    def test_it_asks_for_current_only_and_no_forecast_horizon(self):
        # #120 rules out a time scrubber and per-day grid fields. Asking for `hourly` as well
        # would multiply the response by the forecast horizon for a feature nobody has asked
        # to use, and the store by the same factor.
        seen: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=grid_body())

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            fetch_grid_marine(client)

        params = seen[0].url.params
        assert "current" in params
        assert "hourly" not in params
        assert "forecast_days" not in params

    def test_it_pins_the_units_it_will_check_for(self):
        seen: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=grid_body())

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            fetch_grid_marine(client)

        params = seen[0].url.params
        assert params["timezone"] == TIMEZONE
        assert params["length_unit"] == "metric"
        assert params["wind_speed_unit"] == "kmh"


class TestAGridThatIsNotAGrid:
    """Shape failures: the response is not twenty-five well-formed locations."""

    def test_a_single_object_is_rejected_rather_than_wrapped(self):
        # A grid that silently became one point would be a wind field of one dart, drawn over
        # a map whose other twenty-four squares a reader would take as calm.
        with pytest.raises(ValueError, match="not the list"):
            validate_grid(point_body(), MARINE_VARIABLES, grid_points())

    def test_too_few_locations_is_rejected(self):
        with pytest.raises(ValueError, match="24 grid locations"):
            validate_grid(grid_body(24), MARINE_VARIABLES, grid_points())

    def test_too_many_locations_is_rejected(self):
        with pytest.raises(ValueError, match="26 grid locations"):
            validate_grid(grid_body(26), MARINE_VARIABLES, grid_points())

    def test_a_location_that_is_not_an_object_is_rejected(self):
        payload = grid_body()
        payload[7] = "not a block"
        with pytest.raises(ValueError, match="is not an object"):
            validate_grid(payload, MARINE_VARIABLES, grid_points())


class TestAPointThatIsNotWellFormed:
    """Content failures, each one named by the point it happened at."""

    def _reject(self, index: int, **overrides: Any) -> str:
        payload = grid_body()
        payload[index] = point_body(**overrides)
        with pytest.raises(ValueError) as caught:
            validate_grid(payload, MARINE_VARIABLES, grid_points())
        return str(caught.value)

    def test_a_missing_current_block_fails_the_grid(self):
        message = self._reject(3, current=None)
        assert "no current block" in message

    def test_a_missing_reading_fails_the_grid(self):
        current = {"time": "2026-02-13T09:00", **{n: 1.5 for n in MARINE_VARIABLES}}
        del current["swell_wave_height"]
        message = self._reject(11, current=current)
        assert "missing variables" in message
        assert "swell_wave_height" in message

    def test_a_null_reading_fails_the_grid(self):
        # Present but null is not present. A null reaches the page as a blank, and a blank on
        # a wind field reads as calm rather than as a fault — the same failure the single
        # point's validator was written for after it reached the store once.
        current = {"time": "2026-02-13T09:00", **{n: 1.5 for n in MARINE_VARIABLES}}
        current["sea_surface_temperature"] = None
        message = self._reject(0, current=current)
        assert "null readings" in message
        assert "sea_surface_temperature" in message

    def test_a_missing_observation_time_fails_the_grid(self):
        message = self._reject(24, current={n: 1.5 for n in MARINE_VARIABLES})
        assert "no observation time" in message

    def test_a_missing_unit_fails_the_grid(self):
        units = {"time": "iso8601", "swell_wave_height": "m"}
        message = self._reject(5, current_units=units)
        assert "missing units" in message

    def test_a_wrong_unit_fails_the_grid(self):
        # The rule of thumb compares bare numbers to thresholds written in metres. A height
        # arriving in feet would be three times the number the thresholds expect, and every
        # call on the page would be wrong while every figure still looked plausible.
        units = dict(point_body()["current_units"])
        units["swell_wave_height"] = "ft"
        message = self._reject(9, current_units=units)
        assert "swell_wave_height" in message

    def test_a_response_on_the_wrong_clock_fails_the_grid(self):
        message = self._reject(2, timezone="UTC")
        assert "UTC" in message

    def test_the_failure_names_the_point_it_happened_at(self):
        # Twenty-five near-identical blocks: "a reading is missing" is not a message anybody
        # can act on. The coordinates are what makes it one.
        latitude, longitude = grid_points()[13]
        message = self._reject(13, current={n: 1.5 for n in MARINE_VARIABLES})
        assert f"{latitude},{longitude}" in message


class TestATransportThatMisbehaves:
    def test_a_permanent_error_is_not_retried(self):
        attempts = 0

        def handle(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(404, json={})

        with (
            httpx.Client(transport=httpx.MockTransport(handle)) as client,
            pytest.raises(httpx.HTTPStatusError),
        ):
            fetch_grid(client, URL, MARINE_VARIABLES, sleep=lambda _: None)

        # Asking again will not change the provider's mind, and retrying spends a rate budget
        # the single-point fetch also needs.
        assert attempts == 1

    def test_a_server_error_is_retried_and_then_succeeds(self):
        attempts = 0

        def handle(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, json={})
            return httpx.Response(200, json=grid_body())

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            blocks, _ = fetch_grid(client, URL, MARINE_VARIABLES, sleep=lambda _: None)

        assert attempts == 2
        assert len(blocks) == 25

    def test_a_well_formed_grid_comes_back_whole(self):
        with httpx.Client(transport=transport_for(grid_body())) as client:
            blocks, url = fetch_grid(client, URL, MARINE_VARIABLES, sleep=lambda _: None)

        assert len(blocks) == 25
        assert url.startswith(URL)
        assert all(block["current"]["swell_wave_height"] == 1.5 for block in blocks)


class TestTheStoreHoldsOneGrid:
    """Storage: twenty-five rows, replaced whole, and honest when there is nothing."""

    def _point(self, latitude: float, longitude: float, height: float = 1.5):
        return {
            "latitude": latitude,
            "longitude": longitude,
            "observed_at": "2026-02-13T09:00",
            "readings": {"swell_height": {"value": height, "unit": "m"}},
        }

    def _grid(self, height: float = 1.5):
        return [self._point(lat, lon, height) for lat, lon in grid_points()]

    def test_a_store_that_never_fetched_a_grid_says_so(self, store):
        # **Not twenty-five zeroes.** A grid of zeroes on a wind field reads as a dead calm,
        # which is a claim about the sea; an empty grid is a claim about the installation.
        assert store.latest_conditions_grid() == []

    def test_a_stored_grid_comes_back_whole(self, store):
        store.replace_conditions_grid(self._grid())

        held = store.latest_conditions_grid()
        assert len(held) == 25
        assert {(p["latitude"], p["longitude"]) for p in held} == set(grid_points())

    def test_a_second_run_replaces_the_grid_rather_than_appending(self, store):
        # The table is bounded by its own key. A run that appended would grow it forever and
        # leave the reader picking between two moments.
        store.replace_conditions_grid(self._grid(1.5))
        store.replace_conditions_grid(self._grid(4.2))

        held = store.latest_conditions_grid()
        assert len(held) == 25
        assert {p["readings"]["swell_height"]["value"] for p in held} == {4.2}

    def test_it_refuses_to_clear_the_grid(self, store):
        # A failed fetch leaves the previous grid in place, and the way it does that is by not
        # calling this at all. Clearing by accident is the one thing a caller must not be able
        # to do — an empty grid is indistinguishable from an installation that never ran.
        store.replace_conditions_grid(self._grid())

        with pytest.raises(ValueError, match="leave the previous grid in place"):
            store.replace_conditions_grid([])

        assert len(store.latest_conditions_grid()) == 25

    def test_a_failed_write_leaves_the_old_grid_untouched(self, store):
        # Wholesale in one transaction: a half-written grid would draw some squares from this
        # run and some from the last, and nothing on the page could say which.
        store.replace_conditions_grid(self._grid(1.5))

        broken = self._grid(4.2)
        del broken[17]["observed_at"]
        with pytest.raises(KeyError):
            store.replace_conditions_grid(broken)

        held = store.latest_conditions_grid()
        assert len(held) == 25
        assert {p["readings"]["swell_height"]["value"] for p in held} == {1.5}

    def test_the_rows_come_back_north_to_south_then_west_to_east(self, store):
        # The order `grid_points()` generates, so a reader can lay them out without sorting
        # and two callers cannot disagree about which corner comes first.
        store.replace_conditions_grid(self._grid())

        held = store.latest_conditions_grid()
        assert (held[0]["latitude"], held[0]["longitude"]) == (GRID_NORTH, GRID_WEST)
        assert (held[-1]["latitude"], held[-1]["longitude"]) == (GRID_SOUTH, GRID_EAST)

    def test_every_point_carries_its_own_stamps_and_readings(self, store):
        store.replace_conditions_grid(self._grid())

        held = store.latest_conditions_grid()
        assert len(held) == 25
        for point in held:
            assert point["observed_at"] == "2026-02-13T09:00"
            assert point["fetched_at"]
            assert point["readings"]["swell_height"] == {"value": 1.5, "unit": "m"}


class TestARunFillsTheGrid:
    """The Pipeline Run's side: two more requests, twenty-five more rows (#120)."""

    def test_a_run_stores_the_whole_grid(self, store):
        ingest(store, forecast_provider())

        assert len(store.latest_conditions_grid()) == GRID_SIDE * GRID_SIDE

    def test_the_points_are_the_coordinates_asked_for_not_the_ones_answered(self, store):
        # **The guarantee lives on this test.** Open-Meteo answers with the centre of whichever
        # of its own cells each coordinate fell in, which is up to a few kilometres from the
        # one that was asked for. Storing the provider's would let a dart drift off the drawn
        # map — the exact thing sharing the bathymetry's bounds exists to prevent — and it
        # would do it invisibly, because a point a few kilometres out still looks like a point.
        ingest(store, forecast_provider())

        held = store.latest_conditions_grid()
        assert [(p["latitude"], p["longitude"]) for p in held] == grid_points()

    def test_every_point_carries_the_sea_and_the_air_together(self, store):
        # A dart needs the weather endpoint and a crest needs the marine one, so a point
        # holding only half the readings is a point the map cannot draw.
        ingest(store, forecast_provider())

        held = store.latest_conditions_grid()
        # Without this the loop below is vacuous against an empty grid, which is exactly the
        # state a broken pipeline leaves behind.
        assert held
        for point in held:
            assert point["readings"]["swell_height"]["unit"] == "m"
            assert point["readings"]["wind_speed"]["unit"] == "km/h"
            assert point["readings"]["wind_direction"]["value"] is not None

    def test_each_point_is_dated_by_the_older_of_its_two_endpoints(self, store):
        # The same rule the single point follows: the two endpoints are separate products
        # reporting their own observation times, and dating the pair by the fresher of them
        # would overstate how current half of every dart is. The fixture's marine grid is
        # observed at 00:00, so a weather grid an hour behind it is the one that dates a point.
        ingest(store, weather_grid_observed_at(forecast_provider(), "2026-02-08T23:00"))

        held = store.latest_conditions_grid()
        assert held
        for point in held:
            assert point["observed_at"] == "2026-02-08T23:00"

    def test_the_fresher_endpoint_is_not_the_one_that_dates_a_point(self, store):
        # The other side of the same rule, and the reason it is a second test: "the older of
        # the two" and "whatever the weather endpoint said" agree on the case above and
        # disagree here, so one test alone cannot tell the rule from the coincidence.
        ingest(store, weather_grid_observed_at(forecast_provider(), "2026-02-09T06:00"))

        held = store.latest_conditions_grid()
        assert held
        for point in held:
            assert point["observed_at"] == "2026-02-09T00:00"


class TestAGridThatDoesNotArrive:
    """Losing the map's wind must not cost a traveller the forecast (#120).

    Nothing a Go Call is made of comes from the grid — it is drawn on the map and nowhere
    else. So the trade the ensemble already makes under ADR 0003 applies here with more force:
    a degraded map is worth less than a lost forecast, and losing the second to protect the
    first would be the wrong way round in both directions.
    """

    def test_an_unreachable_grid_does_not_fail_the_run(self, store):
        ingest(store, forecast_provider(grid_status=503))

        assert store.failed_runs() == []

    def test_a_run_that_lost_its_grid_still_stores_its_forecast(self, store):
        ingest(store, forecast_provider(grid_status=503))

        assert store.latest_conditions() is not None
        assert len(store.forecast()) > MINIMUM_FORECAST_HOURS

    def test_an_unreachable_grid_leaves_the_previous_grid_in_place(self, store):
        ingest(store, forecast_provider())
        ingest(store, forecast_provider(grid_status=503))

        held = store.latest_conditions_grid()
        assert len(held) == GRID_SIDE * GRID_SIDE
        assert [(p["latitude"], p["longitude"]) for p in held] == grid_points()

    def test_the_first_run_to_lose_its_grid_stores_no_grid_at_all(self, store):
        # Not twenty-five zeroes, and not twenty-five points with nothing in them. An
        # installation whose first run lost the grid has no wind to draw, and the endpoint
        # above it has to be able to say so.
        ingest(store, forecast_provider(grid_status=503))

        assert store.latest_conditions_grid() == []

    def test_the_lost_grid_is_recorded_under_its_own_source(self, store):
        # #8 requires an unavailable provider to be recorded, and the absence of grid rows
        # does not say what happened: a store with no grid looks identical whether the
        # endpoint was unreachable or the installation has simply never run.
        ingest(store, forecast_provider(grid_status=503))

        lost = [row for row in store.raw_responses() if row["source"] == GRID_UNAVAILABLE]
        assert lost
        assert all(
            json.loads(row["body"])["failure_kind"] == FailureKind.PROVIDER_UNAVAILABLE.value
            for row in lost
        )

    def test_a_grid_that_arrives_malformed_does_not_fail_the_run_either(self, store):
        # **Deliberately unlike the ensemble**, which lets a `ValueError` through because a
        # changed payload must be loud. The grid can afford to be quieter for a specific
        # reason: it rides the same two endpoints as the single offshore point, whose own
        # `validate` still fails the run — so a provider that genuinely changed shape is
        # caught there. What is left for the grid's validator alone is the multi-coordinate
        # envelope, and losing the map over that would cost a forecast that arrived intact.
        ingest(store, malformed_grid(forecast_provider()))

        assert store.failed_runs() == []
        assert store.latest_conditions_grid() == []

    def test_the_record_names_the_endpoint_that_actually_failed(self, store):
        # The URL is the whole provenance of a degradation nothing else reports. Recording a
        # broken weather grid against the marine endpoint would send the one person who ever
        # reads this row to the wrong API.
        ingest(store, malformed_weather_grid(forecast_provider()))

        lost = [row for row in store.raw_responses() if row["source"] == GRID_UNAVAILABLE]
        assert lost
        assert all("weather" not in row["url"] or "marine" not in row["url"] for row in lost)
        assert all(row["url"] == WEATHER_URL for row in lost)

    def test_a_malformed_grid_is_recorded_as_a_payload_we_did_not_recognise(self, store):
        # Quieter than the ensemble is not the same as silent. The record has to distinguish
        # a provider having a bad afternoon from one this system has stopped understanding —
        # the first is waited out, the second means every run until someone looks will lose
        # the map the same way.
        ingest(store, malformed_grid(forecast_provider()))

        lost = [row for row in store.raw_responses() if row["source"] == GRID_UNAVAILABLE]
        assert lost
        assert all(
            json.loads(row["body"])["failure_kind"] == FailureKind.PAYLOAD_UNRECOGNISED.value
            for row in lost
        )


class TestServingTheGrid:
    """The read endpoint the map draws from (#120), and what it must refuse to imply."""

    def freeze(self, monkeypatch, moment: str) -> None:
        monkeypatch.setattr("nazarenow.api.utc_now", lambda: datetime.fromisoformat(moment))

    def test_an_installation_that_never_fetched_a_grid_says_so(self, store, client):
        # 503, on the same terms as the two endpoints beside it. Two hundred with an empty
        # list would be a map with nothing on it, which a reader cannot tell from a map of a
        # calm afternoon — and calm is a claim about the sea rather than about the software.
        response = client.get("/api/conditions/grid")

        assert response.status_code == 503
        assert "grid" in response.json()["detail"].lower()

    def test_it_serves_every_point_at_the_coordinates_the_map_expects(self, store, client):
        ingest(store, forecast_provider())

        points = client.get("/api/conditions/grid").json()["points"]

        assert [(p["latitude"], p["longitude"]) for p in points] == grid_points()

    def test_every_point_carries_its_readings_and_their_units(self, store, client):
        ingest(store, forecast_provider())

        points = client.get("/api/conditions/grid").json()["points"]

        assert points
        for point in points:
            assert point["wind_speed"]["unit"] == "km/h"
            assert point["wind_direction"]["unit"] == "°"
            assert point["swell_height"]["unit"] == "m"
            assert point["swell_period"]["value"] is not None

    def test_the_grid_is_dated_by_its_oldest_point_not_by_its_first(self, store, client):
        """One observation time stands for twenty-five, so it has to be the oldest of them.

        `merge_grid` dates each point by the older of its own two endpoints, and nothing
        promises the provider refreshed all twenty-five cells in one pass. Reading the stamp
        off the first row would let a corner that is hours behind hide under a fresh one --
        the same overstatement `earliest` exists to prevent between the two endpoints, one
        level up. The whole picture is at least this old, or the number is not worth sending.
        """
        stale_corner = 12
        ingest(
            store,
            one_weather_point_observed_at(forecast_provider(), stale_corner, "2026-02-08T18:00"),
        )

        body = client.get("/api/conditions/grid").json()

        assert body["observed_at"] == "2026-02-08T18:00"
        # And the point really is the odd one out, so this cannot pass by every point being old.
        held = store.latest_conditions_grid()
        assert held[stale_corner]["observed_at"] == "2026-02-08T18:00"
        assert {p["observed_at"] for p in held} == {"2026-02-08T18:00", "2026-02-09T00:00"}

    def test_nothing_the_run_stored_is_dropped_on_the_way_out(self, store, client):
        """Every reading held for a point reaches the response.

        Pydantic drops an unmodelled key without a word, so a reading this system pays a
        provider request for, validates the unit of, and writes to disk can vanish between
        the store and the page with nothing anywhere saying so. The check is the stored keys
        against the served ones rather than a list written out here, which would be a third
        place for the same set to be right in.
        """
        ingest(store, forecast_provider())

        stored = set(store.latest_conditions_grid()[0]["readings"])
        served = set(client.get("/api/conditions/grid").json()["points"][0])

        assert stored
        assert stored - served == set()

    def test_it_carries_the_stamps_the_grid_was_fetched_and_observed_at(self, store, client):
        ingest(store, forecast_provider())

        body = client.get("/api/conditions/grid").json()

        assert body["fetched_at"] == store.latest_conditions_grid()[0]["fetched_at"]
        assert body["observed_at"] == store.latest_conditions_grid()[0]["observed_at"]

    def test_a_grid_from_the_last_cycle_is_not_stale(self, store, client, monkeypatch):
        ingest(store, forecast_provider())
        fetched = datetime.fromisoformat(store.latest_conditions_grid()[0]["fetched_at"])
        self.freeze(monkeypatch, (fetched + timedelta(seconds=INTERVAL_SECONDS)).isoformat())

        assert client.get("/api/conditions/grid").json()["stale"] is False

    def test_a_grid_older_than_two_missed_cycles_is_stale(self, store, client, monkeypatch):
        ingest(store, forecast_provider())
        fetched = datetime.fromisoformat(store.latest_conditions_grid()[0]["fetched_at"])
        self.freeze(monkeypatch, (fetched + timedelta(seconds=STALE_AFTER_SECONDS + 1)).isoformat())

        assert client.get("/api/conditions/grid").json()["stale"] is True

    def test_it_states_how_old_is_too_old(self, store, client):
        # Sent so the interface can name the figure without knowing it, the same reason the
        # other two endpoints send it.
        ingest(store, forecast_provider())

        assert client.get("/api/conditions/grid").json()["stale_after_hours"] == STALE_AFTER_HOURS

    def test_a_grid_left_behind_by_a_failed_fetch_reports_its_own_age(
        self, store, client, monkeypatch
    ):
        """**The test the whole degraded path rests on.**

        A run whose grid fetch failed is a success: its forecast arrived, and the previous
        grid is still there. So the conditions beside it are fresh while the wind on the map
        is two cycles old, and the only thing that can say so is the grid's own `fetched_at`.
        Reporting the run's stamp here would present last night's wind as this morning's.
        """
        ingest(store, forecast_provider())
        grid_fetched = datetime.fromisoformat(store.latest_conditions_grid()[0]["fetched_at"])

        later = grid_fetched + timedelta(seconds=STALE_AFTER_SECONDS + 1)
        self.freeze(monkeypatch, later.isoformat())
        ingest(store, forecast_provider(grid_status=503))

        grid = client.get("/api/conditions/grid").json()
        assert grid["fetched_at"] == grid_fetched.isoformat()
        assert grid["stale"] is True

    # ADR 0005's "nothing in the request path contacts a provider" is not asserted here. It is
    # enforced for the whole suite by `conftest.block_outbound_network`, and a test restating it
    # with `status_code == 200` would add no way for it to fail -- while reading, in a list of
    # test names, like the thing actually holding the guarantee up.
