"""Watch, Go Call and Confirmed statuses, driven at the agreed backend seam.

Everything here goes through the HTTP API. An earlier version called the Amplification
Model directly, which was a seam breach with no justification: every property asserted
below — status, reasons, predicted height — is observable through the API, so the
exception `Store.raw_responses()` earns ("nothing else can observe it") does not apply.

Thresholds are pinned at their boundaries, both sides. Testing only "a giant setup
matches and a flat one does not" left every threshold value and every comparison operator
free: 3m could become 2m or 4m, and >= could become >, with the suite still green.
"""

from __future__ import annotations

import pytest

from helpers import GIANT, QUIET, forecast_provider, ingest

# Literals, deliberately. Importing the constants and testing `CONSTANT - 0.1` looks
# rigorous and pins nothing: change the constant and both sides of the assertion move
# with it. These are the values the rule of thumb actually specifies, so a silent
# retuning of any threshold fails here — which is the point, since ticket #12 will
# retune them deliberately and should have to say so.
HEIGHT_M = 3.0
PERIOD_S = 14.0
SWELL_ARC_FROM, SWELL_ARC_TO = 255.0, 330.0
WIND_ARC_FROM, WIND_ARC_TO = 20.0, 180.0
MAX_WIND_KMH = 35.0
CONFIRMED_LEAD = 1
GO_LEAD = 7

TODAY = "2026-02-09"
SOON = "2026-02-13"  # lead 4: inside the Go band
FAR = "2026-02-20"  # lead 11: beyond it


def calls(client) -> dict[str, dict]:
    body = client.get("/api/conditions/forecast").json()
    return {day["date"]: day["call"] for day in body["days"]}


def status_for(store, client, conditions: dict, date: str = SOON, **kwargs) -> str:
    ingest(store, forecast_provider({date: conditions}, today=TODAY, **kwargs))
    return calls(client)[date]["status"]


class TestThresholdBoundaries:
    """Each threshold, one increment either side of its boundary."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(HEIGHT_M, "go"), (HEIGHT_M - 0.1, "none")],
    )
    def test_wave_height_boundary(self, store, client, value, expected) -> None:
        assert status_for(store, client, {**GIANT, "significant_wave_height": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(PERIOD_S, "go"), (PERIOD_S - 0.1, "none")],
    )
    def test_swell_period_boundary(self, store, client, value, expected) -> None:
        assert status_for(store, client, {**GIANT, "swell_period": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (SWELL_ARC_FROM, "go"),
            (SWELL_ARC_FROM - 1, "none"),
            (SWELL_ARC_TO, "go"),
            (SWELL_ARC_TO + 1, "none"),
        ],
    )
    def test_swell_direction_arc_edges(self, store, client, value, expected) -> None:
        assert status_for(store, client, {**GIANT, "swell_direction": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (WIND_ARC_FROM, "go"),
            (WIND_ARC_FROM - 1, "watch"),
            (WIND_ARC_TO, "go"),
            (WIND_ARC_TO + 1, "watch"),
        ],
    )
    def test_offshore_wind_arc_edges(self, store, client, value, expected) -> None:
        """Wind outside the arc withholds a Go Call but not a Watch — the swell is still
        worth watching, which is the distinction ADR 0003 asks for."""
        assert status_for(store, client, {**GIANT, "wind_direction": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(MAX_WIND_KMH, "go"), (MAX_WIND_KMH + 0.1, "watch")],
    )
    def test_wind_speed_boundary(self, store, client, value, expected) -> None:
        assert status_for(store, client, {**GIANT, "wind_speed": value}) == expected


class TestLeadTimeBands:
    """Each tier boundary, one day either side."""

    def test_confirmed_band_upper_edge(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-10": GIANT, "2026-02-11": GIANT}, today=TODAY))
        issued = calls(client)

        assert issued["2026-02-10"]["lead_time_days"] == CONFIRMED_LEAD
        assert issued["2026-02-10"]["status"] == "confirmed"
        assert issued["2026-02-11"]["status"] == "go"

    def test_go_band_upper_edge(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-16": GIANT, "2026-02-17": GIANT}, today=TODAY))
        issued = calls(client)

        assert issued["2026-02-16"]["lead_time_days"] == GO_LEAD
        assert issued["2026-02-16"]["status"] == "go"
        assert issued["2026-02-17"]["status"] == "watch"

    def test_today_is_confirmed(self, store, client) -> None:
        assert status_for(store, client, GIANT, date=TODAY) == "confirmed"


class TestWatchIsLooserThanGo:
    """ADR 0003 optimises a Watch for recall and a Go Call for precision. Gating both on
    every condition made them one rule with two names, differing only by lead time."""

    def test_a_building_swell_with_wrong_wind_still_raises_a_watch(self, store, client) -> None:
        assert status_for(store, client, {**GIANT, "wind_direction": 270}, date=FAR) == "watch"

    def test_wind_alone_never_earns_a_go_call(self, store, client) -> None:
        assert status_for(store, client, {**GIANT, "wind_direction": 270}, date=SOON) == "watch"

    def test_a_flat_swell_raises_nothing_however_perfect_the_wind(self, store, client) -> None:
        assert status_for(store, client, QUIET, date=FAR) == "none"

    def test_a_swell_failing_only_direction_raises_nothing(self, store, client) -> None:
        """Direction is a swell condition, so unlike wind it does gate the Watch."""
        assert status_for(store, client, {**GIANT, "swell_direction": 200}, date=FAR) == "none"


class TestCallContent:
    def test_a_call_is_judged_on_the_best_matching_hour_not_the_peak(self, store, client) -> None:
        """The biggest hour of the day is not always the one worth travelling for.

        Here 15:00 is the largest sea but blows onshore, while 09:00 is smaller and clean.
        Judging the peak alone returns no call and discards a real window; judging the
        best matching hour surfaces it. A fixture whose matching window *is* the peak
        cannot tell those apart, which is how this went unpinned.
        """
        ingest(
            store,
            forecast_provider(
                {SOON: {**GIANT, "significant_wave_height": 3.4}},
                today=TODAY,
                only_hours={SOON: (9, 10, 11)},
                peak_but_onshore={SOON: (15,)},
            ),
        )

        assert calls(client)[SOON]["status"] == "go"

    def test_a_call_explains_itself(self, store, client) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        reasons = calls(client)[SOON]["reasons"]

        assert any("significant wave height" in reason for reason in reasons)
        assert any("swell period" in reason for reason in reasons)
        assert any("wind" in reason for reason in reasons)

    def test_a_call_reports_the_significant_wave_height_it_judged(self, store, client) -> None:
        """The reported height must be the Significant Wave Height the rule was applied
        to, not the swell height — CONTEXT.md lists those as different variables, and the
        interface labels this one as the instrument's measure of the sea."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        assert calls(client)[SOON]["predicted_significant_wave_height"] == {
            "value": GIANT["significant_wave_height"],
            "unit": "m",
        }

    @pytest.mark.parametrize("height", [3.0, 4.2, 7.5])
    def test_the_baseline_never_scales_the_height_it_was_given(self, store, client, height) -> None:
        """The canyon's threefold amplification applies to Face Height, a different
        quantity. Asserting merely that the number was "not enormous" let a 1.5x and even
        a 1.9x multiple through; equality is the property that matters."""
        ingest(
            store,
            forecast_provider({SOON: {**GIANT, "significant_wave_height": height}}, today=TODAY),
        )

        assert calls(client)[SOON]["predicted_significant_wave_height"]["value"] == height

    def test_calls_declare_that_their_thresholds_are_uncalibrated(self, store, client) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        body = client.get("/api/conditions/forecast").json()

        assert body["calibrated"] is False
        assert body["amplification_model"] == "heuristic-baseline"


class TestCallsArePersisted:
    def test_the_api_serves_calls_it_did_not_compute(self, store, client) -> None:
        """ADR 0005 makes the API a reader and a Pipeline Run the only thing that runs a
        model. It also promises every prediction is retained, which is the record ticket
        #11 needs to score Go Call precision. Deriving calls per request kept none."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        stored = store.calls()

        assert stored[SOON]["status"] == "go"
        assert stored[SOON]["issued_for_date"] == TODAY
        assert stored[SOON]["issued_at"]

    def test_a_stale_forecast_reports_the_lead_time_it_was_issued_at(self, store, client) -> None:
        """Lead Time is fixed when the call is issued, so a forecast left sitting cannot
        present an already-elapsed Go Call as fresh advice."""
        ingest(store, forecast_provider({"2020-01-05": GIANT}, today="2020-01-01"))

        assert calls(client)["2020-01-05"]["lead_time_days"] == 4
        assert store.calls()["2020-01-05"]["issued_for_date"] == "2020-01-01"

    def test_no_calls_yet_is_reported_rather_than_faked(self, client) -> None:
        assert client.get("/api/conditions/forecast").status_code == 503
