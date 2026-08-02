"""The Heuristic Baseline returns a fixed result for fixed inputs.

Ticket #11 requires this and requires the backtest itself to stay *out* of the suite: an
assertion that fails when accuracy shifts slightly gets disabled within weeks and blocks
legitimate experimentation. So nothing here asserts an accuracy figure.

What it pins is the thing that would make the committed benchmark quietly wrong. The report
in `analysis/backtest/` scores this exact class and prints numbers a reader is invited to
trust. Change a threshold or an arc and those numbers describe a rule that no longer exists,
with nothing anywhere saying so. These tests fail instead, and the failure message says to
re-run the backtest.

Per ADR 0006 the baseline is permanent, so pinning it is not friction against a moving part
— it is the point of keeping it.
"""

from __future__ import annotations

import pytest

from nazarenow.decision import Status, decide
from nazarenow.models.heuristic import (
    MAXIMUM_WIND_SPEED_KMH,
    MINIMUM_SWELL_PERIOD_S,
    MINIMUM_WAVE_HEIGHT_M,
    OFFSHORE_WIND_ARC,
    SWELL_ARC,
    HeuristicBaseline,
)

RERUN = (
    "the committed backtest in analysis/backtest/ now describes a rule that no longer "
    "exists — re-run it"
)

# A day clearing every condition, and comfortably so: nothing here sits near a boundary, so
# this fixture keeps meaning the same thing if #12 nudges a threshold.
GIANT = {
    "significant_wave_height": 5.0,
    "swell_period": 16.0,
    "swell_direction": 300.0,
    "wind_speed": 10.0,
    "wind_direction": 90.0,
}


def test_thresholds_are_what_the_backtest_scored() -> None:
    """The published benchmark rests on these five numbers."""
    assert MINIMUM_WAVE_HEIGHT_M == 3.0, RERUN
    assert MINIMUM_SWELL_PERIOD_S == 14.0, RERUN
    assert SWELL_ARC == (255.0, 330.0), RERUN
    assert OFFSHORE_WIND_ARC == (20.0, 180.0), RERUN
    assert MAXIMUM_WIND_SPEED_KMH == 35.0, RERUN


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
    ("change", "expected_failure"),
    [
        ({"significant_wave_height": 2.9}, "significant wave height"),
        ({"swell_period": 13.9}, "swell period"),
        ({"swell_direction": 254.0}, "swell direction"),
        ({"swell_direction": 331.0}, "swell direction"),
        ({"wind_direction": 270.0}, "wind"),
        ({"wind_speed": 35.1}, "wind"),
    ],
)
def test_one_condition_short_of_the_rule(change: dict[str, float], expected_failure: str) -> None:
    """Each condition is load-bearing on its own.

    Written as one departure from a passing day at a time, because a fixture that fails two
    conditions at once cannot tell a broken condition from a redundant one.
    """
    prediction = HeuristicBaseline().predict(GIANT | change)

    assert not prediction.matches_rule
    failed = [o.condition.value for o in prediction.conditions if not o.holds]
    assert failed == [expected_failure]


def test_the_baseline_reports_itself_uncalibrated() -> None:
    """Until #12 fits the thresholds to Gold Days, the interface must not imply otherwise."""
    assert HeuristicBaseline().name == "heuristic-baseline"
    assert HeuristicBaseline().calibrated is False


def test_a_giant_day_earns_a_go_call_and_a_flat_day_earns_nothing() -> None:
    """The pairing ticket #12's own criteria ask for, at the Lead Time the backtest uses."""
    giant = decide(HeuristicBaseline().predict(GIANT), lead_time_days=3)
    flat = decide(HeuristicBaseline().predict(GIANT | {"swell_period": 8.0}), lead_time_days=3)

    assert giant.status is Status.GO
    assert flat.status is Status.NONE
