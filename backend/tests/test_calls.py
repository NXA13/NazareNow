"""Watch, Go Call and Confirmed statuses, driven at the agreed backend seam.

Providers are stubbed at the HTTP boundary, a Pipeline Run executes, and the calls are
read back through the API. The Amplification Model and the Decision Model are internal
to this seam and may be restructured freely.
"""

from __future__ import annotations

import pytest

from helpers import forecast_provider, ingest
from nazarenow.models import HeuristicBaseline
from nazarenow.models.base import Prediction

# The surf community's rule of thumb for Nazare, per ADR 0006: a big swell, a long
# period, arriving from the west-north-west, with light offshore wind. Each fixture below
# breaks exactly one of those, so a rule that ignored any single condition would show.
GIANT = {
    "swell_height": 4.2,
    "swell_period": 16.5,
    "swell_direction": 298,
    "wind_speed": 11.0,
    "wind_direction": 110,
}
FLAT = {**GIANT, "swell_height": 1.1, "swell_period": 7.0}
SHORT_PERIOD = {**GIANT, "swell_period": 9.0}
WRONG_DIRECTION = {**GIANT, "swell_direction": 200}
ONSHORE_WIND = {**GIANT, "wind_direction": 270}
HOWLING_WIND = {**GIANT, "wind_speed": 55.0}


def call_for(client, date: str) -> dict:
    body = client.get("/api/conditions/forecast").json()
    return next(day for day in body["days"] if day["date"] == date)["call"]


class TestHeuristicBaseline:
    def test_it_is_deterministic_for_fixed_inputs(self) -> None:
        """ADR 0006 keeps this permanently as the benchmark a learned model must beat.
        A benchmark that moves is not a benchmark."""
        model = HeuristicBaseline()

        first = model.predict(GIANT)
        second = model.predict(GIANT)

        assert first == second

    def test_it_predicts_conditions_at_praia_do_norte(self) -> None:
        model = HeuristicBaseline()

        prediction = model.predict(GIANT)

        assert isinstance(prediction, Prediction)
        assert prediction.significant_wave_height > 0
        assert prediction.unit == "m"

    def test_it_does_not_invent_face_height(self) -> None:
        """The canyon's famous threefold amplification applies to Face Height, which is
        what an observer sees. This model predicts Significant Wave Height, which is a
        different quantity — CONTEXT.md holds them apart deliberately. Multiplying Hs by
        a face-height factor would produce a confident, plausible, wrong number."""
        model = HeuristicBaseline()

        prediction = model.predict(GIANT)

        assert prediction.significant_wave_height < GIANT["swell_height"] * 2

    def test_a_giant_setup_matches_every_condition(self) -> None:
        model = HeuristicBaseline()

        prediction = model.predict(GIANT)

        assert prediction.unmatched == ()
        assert len(prediction.matched) == 4

    @pytest.mark.parametrize(
        ("conditions", "expected"),
        [
            (SHORT_PERIOD, "period"),
            (WRONG_DIRECTION, "direction"),
            (ONSHORE_WIND, "wind direction"),
            (HOWLING_WIND, "wind speed"),
            (FLAT, "swell height"),
        ],
    )
    def test_it_names_the_condition_that_failed(self, conditions, expected) -> None:
        """Each status has to explain itself. A verdict with no reason is not advice."""
        model = HeuristicBaseline()

        prediction = model.predict(conditions)

        assert any(expected in reason for reason in prediction.unmatched), (
            f"expected {expected!r} among {prediction.unmatched}"
        )


class TestCalls:
    def test_a_matching_setup_close_in_produces_a_go_call(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today="2026-02-09"))

        call = call_for(client, "2026-02-13")

        assert call["status"] == "go"
        assert call["lead_time_days"] == 4

    def test_a_matching_setup_far_out_produces_a_watch(self, store, client) -> None:
        """Optimised for recall: at long range a forming swell is worth watching even
        though the forecast cannot yet justify spending money."""
        ingest(store, forecast_provider({"2026-02-20": GIANT}, today="2026-02-09"))

        call = call_for(client, "2026-02-20")

        assert call["status"] == "watch"

    def test_a_matching_setup_today_is_confirmed(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-09": GIANT}, today="2026-02-09"))

        call = call_for(client, "2026-02-09")

        assert call["status"] == "confirmed"

    def test_quiet_conditions_produce_no_call(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-13": FLAT}, today="2026-02-09"))

        call = call_for(client, "2026-02-13")

        assert call["status"] == "none"

    @pytest.mark.parametrize(
        "conditions", [SHORT_PERIOD, WRONG_DIRECTION, ONSHORE_WIND, HOWLING_WIND]
    )
    def test_one_failed_condition_withholds_the_go_call(self, store, client, conditions) -> None:
        """A Go Call costs the user a flight. Every condition has to hold."""
        ingest(store, forecast_provider({"2026-02-13": conditions}, today="2026-02-09"))

        assert call_for(client, "2026-02-13")["status"] != "go"

    def test_every_call_explains_itself(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today="2026-02-09"))

        call = call_for(client, "2026-02-13")

        assert call["reasons"], "a call with no reasons is not advice"
        assert any("period" in reason for reason in call["reasons"])

    def test_a_call_reports_the_predicted_conditions_not_only_the_forecast(
        self, store, client
    ) -> None:
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today="2026-02-09"))

        call = call_for(client, "2026-02-13")

        assert call["predicted_significant_wave_height"]["unit"] == "m"
        assert call["predicted_significant_wave_height"]["value"] > 0

    def test_calls_declare_that_their_thresholds_are_uncalibrated(self, store, client) -> None:
        """Ticket #12 calibrates these against Gold Days. Until then the numbers are a
        rule of thumb, and the API says so rather than letting the interface imply
        otherwise."""
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today="2026-02-09"))

        body = client.get("/api/conditions/forecast").json()

        assert body["calibrated"] is False
        assert body["model"] == "heuristic-baseline"
