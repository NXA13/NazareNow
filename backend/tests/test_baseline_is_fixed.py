"""The Heuristic Baseline returns a fixed result for fixed inputs.

Ticket #11 requires this and requires the backtest itself to stay *out* of the suite: an
assertion that fails when accuracy shifts slightly gets disabled within weeks and blocks
legitimate experimentation. So nothing here asserts an accuracy figure.

What it pins is the thing that would make the committed reports quietly wrong. The backtest
in `analysis/backtest/` and the calibration in `analysis/calibration/` both score this exact
class and print numbers a reader is invited to trust. Change a threshold or an arc and those
numbers describe a rule that no longer exists, with nothing anywhere saying so. These tests
fail instead, and the failure message says to re-run them.

Since ticket #12 the thresholds live in `thresholds.json` rather than in module constants,
so what is pinned here is the shipped file — which is exactly the thing a recalibration
changes, and exactly the thing the reports depend on.

Per ADR 0006 the baseline is permanent, so pinning it is not friction against a moving part
— it is the point of keeping it.
"""

from __future__ import annotations

import pytest

from nazarenow.decision import Status, decide
from nazarenow.models.base import Prediction
from nazarenow.models.heuristic import HeuristicBaseline
from nazarenow.thresholds import load

RERUN = (
    "the committed reports in analysis/backtest/ and analysis/calibration/ now describe a "
    "rule that no longer exists — re-run them"
)

SHIPPED = load()

# A day clearing every condition, and comfortably so: nothing here sits near a boundary, so
# this fixture keeps meaning the same thing if a later recalibration nudges a threshold.
#
# The wind sits above `light_wind_exemption_kmh` on purpose. Since ADR 0009 the condition can
# hold two ways, and at 10 km/h this day held by being too calm to care about — which meant
# the direction row below tested nothing, because changing the bearing of an exempt wind
# changes no verdict.
GIANT = {
    "significant_wave_height": 5.0,
    "swell_period": 16.0,
    "swell_direction": 300.0,
    "wind_speed": 18.0,
    "wind_direction": 90.0,
}


def test_thresholds_are_what_the_reports_scored() -> None:
    """The published numbers rest on these seven values.

    Refitted by #39 against 38 Gold Days rather than #12's 9, on the Copernicus reanalysis,
    and translated back into Open-Meteo units on the way out. `light_wind_exemption_kmh` is
    new in ADR 0009 and is the only one read in the units it was fitted in — wind comes from
    ERA5 on both sides of that translation.
    """
    assert SHIPPED.minimum_significant_wave_height_m == 2.75, RERUN
    assert SHIPPED.watch_minimum_swell_period_s == 10.1, RERUN
    assert SHIPPED.go_call_minimum_swell_period_s == 12.9, RERUN
    assert SHIPPED.swell_arc == (255.0, 330.0), RERUN
    assert SHIPPED.offshore_wind_arc == (20.0, 180.0), RERUN
    assert SHIPPED.maximum_wind_speed_kmh == 35.0, RERUN
    assert SHIPPED.light_wind_exemption_kmh == 16.5, RERUN


def test_the_shipped_thresholds_carry_their_provenance() -> None:
    """A calibration the interface can describe, per #12.

    The interface tells the user how few Gold Days these rest on. It can only do that if
    the number travels with the thresholds, so a file that dropped it would be a silent
    regression in what the user is told rather than a crash.
    """
    calibration = SHIPPED.calibration

    assert calibration is not None, RERUN
    assert calibration.gold_days_fitted == 25
    assert calibration.gold_days_validated == 13
    assert calibration.gold_days_total == 38
    assert calibration.fitted_on != calibration.validated_on
    assert calibration.source == "analysis/calibration/calibrate.py"


def test_a_giant_day_matches_every_condition() -> None:
    prediction = HeuristicBaseline().predict(GIANT)

    assert prediction.matches_rule
    assert prediction.significant_wave_height == 5.0
    assert prediction.unit == "m"
    assert prediction.unmatched == ()


def test_the_same_readings_always_give_the_same_answer() -> None:
    """Deterministic, which is what lets a backtest be re-run and compared."""
    first = HeuristicBaseline().predict(GIANT)
    second = HeuristicBaseline().predict(dict(GIANT))

    assert first == second


@pytest.mark.parametrize(
    ("change", "expected_failures"),
    [
        ({"significant_wave_height": 2.74}, ["significant wave height"]),
        # Below the Watch bar fails both period conditions, because a period too short to
        # watch is necessarily too short to book on. Asserting the pair rather than one of
        # them is what would catch the two bars being wired to the same number.
        ({"swell_period": 10.0}, ["swell period", "swell period for a go call"]),
        # Between the bars: worth a Watch, not worth a Go Call. This row is the tier split.
        ({"swell_period": 12.8}, ["swell period for a go call"]),
        ({"swell_direction": 254.0}, ["swell direction"]),
        ({"swell_direction": 331.0}, ["swell direction"]),
        # Onshore *and* windy enough that the ADR 0009 exemption does not rescue it. Both
        # halves matter: at 16.5 km/h or below this bearing would hold.
        ({"wind_direction": 270.0}, ["wind"]),
        ({"wind_speed": 35.1}, ["wind"]),
    ],
)
def test_one_condition_short_of_the_rule(
    change: dict[str, float], expected_failures: list[str]
) -> None:
    """Each condition is load-bearing on its own.

    Written as one departure from a passing day at a time, because a fixture that fails two
    conditions at once cannot tell a broken condition from a redundant one.
    """
    prediction = HeuristicBaseline().predict(GIANT | change)

    assert not prediction.matches_rule
    failed = [o.condition.value for o in prediction.conditions if not o.holds]
    assert failed == expected_failures


class TestTheLightWindExemption:
    """ADR 0009: below the exemption speed, direction stops being consulted.

    The defect this fixes rejected six documented XXL Days on breezes of 4-16 km/h that
    happened to blow from the wrong quarter — the rule claimed they were unsurfable.
    """

    def test_a_wind_too_light_to_matter_holds_from_any_direction(self) -> None:
        onshore = GIANT | {"wind_speed": 4.1, "wind_direction": 225.0}

        prediction = HeuristicBaseline().predict(onshore)

        assert prediction.matches_rule
        assert prediction.unmatched == ()

    def test_the_exemption_stops_exactly_at_its_speed(self) -> None:
        """Checked from both sides, so a `<` written for a `<=` fails here.

        2020-02-17 is the Gold Day that set this bar: its calmest hour was 16.3 km/h, and a
        comparison one step tight would put it back outside the rule that was changed to
        admit it.
        """
        model = HeuristicBaseline()
        at_the_bar = GIANT | {"wind_speed": 16.5, "wind_direction": 225.0}
        just_over = GIANT | {"wind_speed": 16.6, "wind_direction": 225.0}

        assert model.predict(at_the_bar).matches_rule
        assert not model.predict(just_over).matches_rule

    def test_an_onshore_gale_still_fails(self) -> None:
        """The exemption must not have quietly become a licence for any onshore wind."""
        prediction = HeuristicBaseline().predict(
            GIANT | {"wind_speed": 30.0, "wind_direction": 270.0}
        )

        assert not prediction.matches_rule
        assert [o.condition.value for o in prediction.conditions if not o.holds] == ["wind"]

    def test_the_two_ways_of_holding_say_different_things(self) -> None:
        """A day that passes because the air is still is not a day groomed by an offshore
        breeze, and somebody deciding whether to fly to Portugal is owed the difference."""
        model = HeuristicBaseline()
        becalmed = model.predict(GIANT | {"wind_speed": 4.0, "wind_direction": 225.0})
        groomed = model.predict(GIANT)

        def wind_sentence(prediction: Prediction) -> str:
            return next(o.explanation for o in prediction.conditions if o.condition.value == "wind")

        assert "too light to matter" in wind_sentence(becalmed)
        assert "offshore and light" in wind_sentence(groomed)

    def test_an_onshore_failure_says_why_the_exemption_did_not_apply(self) -> None:
        """Otherwise a reader cannot tell why a 20 km/h breeze was judged differently from
        the 12 km/h one an hour earlier."""
        prediction = HeuristicBaseline().predict(
            GIANT | {"wind_speed": 20.0, "wind_direction": 270.0}
        )

        explanation = next(
            o.explanation for o in prediction.conditions if o.condition.value == "wind"
        )
        assert "onshore" in explanation
        assert "16.5" in explanation


def test_the_baseline_reports_itself_calibrated() -> None:
    """#12 fitted the thresholds, so the interface's caveat comes down.

    Read from the threshold file's provenance rather than asserted by the model, so this
    cannot pass for a model whose numbers came from nowhere.
    """
    assert HeuristicBaseline().name == "heuristic-baseline"
    assert HeuristicBaseline().calibrated is True


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        (13.0, Status.GO),
        (12.9, Status.GO),
        (12.8, Status.WATCH),
        (10.1, Status.WATCH),
        (10.0, Status.NONE),
    ],
)
def test_the_calibrated_period_decides_the_tier(period: float, expected: Status) -> None:
    """Above the calibrated Go Call bar earns a Go Call; below it does not.

    #12's own acceptance criterion, written across both bars because the ticket's point was
    that there are now two. Each bar is checked from both sides at the tightest step the
    calibration's own resolution supports, so a comparison silently written as `>` rather
    than `>=` fails here rather than in a season's worth of forecasts.
    """
    call = decide(HeuristicBaseline().predict(GIANT | {"swell_period": period}), lead_time_days=3)

    assert call.status is expected


def test_a_giant_day_earns_a_go_call_and_a_flat_day_earns_nothing() -> None:
    """The pairing ticket #12's criteria ask for, at the Lead Time the backtest uses."""
    giant = decide(HeuristicBaseline().predict(GIANT), lead_time_days=3)
    flat = decide(HeuristicBaseline().predict(GIANT | {"swell_period": 8.0}), lead_time_days=3)

    assert giant.status is Status.GO
    assert flat.status is Status.NONE


def test_the_tiers_cannot_collapse_into_one_rule() -> None:
    """A Watch must be reachable without a Go Call, which is what #11 found it was not.

    Guards the defect directly rather than through the thresholds that currently avoid it:
    if a later recalibration set both bars to the same number, every Watch day would also
    be a Go Call day and ADR 0003's two tiers would be one rule with two names again.
    `thresholds.parse` refuses such a file, and this is the behavioural half of that.
    """
    assert SHIPPED.go_call_minimum_swell_period_s > SHIPPED.watch_minimum_swell_period_s

    between = (SHIPPED.watch_minimum_swell_period_s + SHIPPED.go_call_minimum_swell_period_s) / 2
    call = decide(HeuristicBaseline().predict(GIANT | {"swell_period": between}), lead_time_days=3)

    assert call.status is Status.WATCH
