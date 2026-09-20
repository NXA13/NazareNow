"""The grid of conditions the map is drawn from (#120).

Twenty-five points over exactly the frame the map draws, fetched in one request per API and
held to the same standard as the single offshore point: a missing reading, a null one, or one
in an unexpected unit fails the grid rather than reaching the store.

**The failure these tests are really about is the quiet one.** A dropped reading does not look
like a fault on a wind field — it looks like calm weather, which is the most dangerous thing
this map could say. So the validation cases outnumber the happy path here on purpose.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

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

        for point in store.latest_conditions_grid():
            assert point["observed_at"] == "2026-02-13T09:00"
            assert point["fetched_at"]
            assert point["readings"]["swell_height"] == {"value": 1.5, "unit": "m"}
