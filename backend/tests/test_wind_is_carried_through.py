"""Wind reaches the model unperturbed, and that omission stays cheap enough to justify.

Ticket #68. #15's first criterion asks that "forecast **inputs** are perturbed using the
measured Forecast Error Profile for that Lead Time", and `ErrorBudget.distribution` perturbs
exactly one: the Combined Sea. Four of the other seven features are unavoidable — ADR 0004's
#14 amendment records that the Swell partition is not archived at any Lead Time, so there is
no profile to perturb them by. **Wind is archived**, out to four trustworthy days, and is
left fixed anyway.

`distribution.py` now says so and says what it costs. These tests are what stop that from being
a sentence nobody checks — the failure mode #64 is the standing issue for.

The first pins the behaviour: if a later change starts perturbing wind, the claim in
`distribution.py` becomes false and this fails rather than the docs quietly going stale.

The second and third pin the *justification*, which is the load-bearing half. "We measured it
and it is negligible" and "we did not think about it" are different states, and only the first
survives the wind coefficient growing, a re-measured profile coming in wider, or a refit
introducing a wind feature nobody priced.
"""

from __future__ import annotations

from nazarenow.distribution import SEA, ErrorBudget
from nazarenow.models.base import Prediction
from nazarenow.models.learned import LearnedAmplification

GIANT = {
    "significant_wave_height": 5.0,
    "swell_height": 4.4,
    "swell_period": 16.0,
    "swell_direction": 300.0,
    "wind_speed": 18.0,
    "wind_direction": 90.0,
}

WIND_SPEED_DRIFT_KMH = 8.75
WIND_DIRECTION_DRIFT_DEG = 39.9
"""The widest drift #14 measured for each wind variable inside the trustworthy window.

Both are lead-4 rows of `analysis/forecast_error/output/drift_by_lead_time.csv`, and they come
from **different regimes**: speed is widest on big swell at 8.7522 km/h, direction on all hours
at 39.8536°. Taking each variable's own maximum makes this a harder question than any single
row of the archive asks, which is the right way round for a bound.

The pairing is not obvious and was got wrong first time here — big swell is the regime this
project exists to call, so it reads as the wider one everywhere, and for direction it is not
(36.4724° against 39.8536°).

Lead 4 rather than lead 7 because README finding 4 shows leads 5 and 6 carry a provider
artefact rather than weather, so the profile past four days is not evidence about anything.
"""

STATED_COST_M = 0.15
"""What a full one-sigma shift in both wind variables is allowed to move a prediction by.

The shipped coefficients produce 0.111 m on this fixture and 0.119 m on the ordinary one
`wind_sensitivity.py` also measures, so the wind term has to grow by **35%** before this
trips — wide enough that an ordinary refit does not, narrow enough that a term growing by
half does. An earlier version of this said "about 25%" and "a third would": #75 measured the
headroom at 34.9%, so a third leaves 0.148 m and passes. The bound is stated rather than
derived, so the sensitivity it buys is worth stating correctly.

This is a bound on the *mechanism*, not on the conclusion. What `distribution.py` states is
the conclusion — 0.28% to 0.96% of the plausible range's width — and that comes from
`analysis/forecast_error/wind_sensitivity.py`, which perturbs and re-samples rather than
shifting. A bound is checked here instead because the shift is what the conclusion rests on
and it needs no sampler: reproducing one in the test suite would be a second sampler to keep
in step with the first, which is the shape of defect #67 has just finished removing. It would
also be the harder thing to get right — the script's own first attempt at that sampler
measured its sampling error rather than wind, and only a sweep across seeds showed it.
"""

RERUN = (
    "wind is no longer the negligible omission distribution.py says it is — re-run "
    "analysis/forecast_error/wind_sensitivity.py and revisit whether it should be perturbed"
)


class RecordingModel:
    """Stands in for the Amplification Model and keeps every reading it was handed."""

    name = "recording"
    calibrated = False

    def __init__(self) -> None:
        self.seen: list[dict[str, float]] = []

    def predict(self, readings: dict[str, float]) -> Prediction:
        self.seen.append(dict(readings))
        return Prediction(significant_wave_height=float(readings[SEA]))


def test_every_draw_sees_the_forecasts_own_wind() -> None:
    """The Combined Sea moves across draws; wind does not.

    Both halves matter. Without the first, a broken sampler that perturbed nothing would
    pass this file while producing a range of zero width.
    """
    model = RecordingModel()
    ErrorBudget.shipped().distribution(model, GIANT, lead_time_days=3, draws=50)

    speeds = {reading["wind_speed"] for reading in model.seen}
    directions = {reading["wind_direction"] for reading in model.seen}
    seas = {reading[SEA] for reading in model.seen}

    assert speeds == {GIANT["wind_speed"]}, (
        "wind speed varies across draws, so the distribution now perturbs it; "
        "distribution.py documents the opposite"
    )
    assert directions == {GIANT["wind_direction"]}, (
        "wind direction varies across draws, so the distribution now perturbs it; "
        "distribution.py documents the opposite"
    )
    assert len(seas) > 1, "the Combined Sea is not being perturbed at all"


def test_a_full_wind_drift_moves_the_prediction_less_than_the_stated_cost() -> None:
    """Shift both wind variables by the widest drift #14 trusts, and read what it does.

    Shifted rather than sampled, and both at once, so this is the worst a one-sigma wind
    error can do rather than an average — the number that has to be small for the omission
    to be defensible.
    """
    model = LearnedAmplification()
    base = model.predict(GIANT).significant_wave_height

    moved = max(
        abs(
            model.predict(
                {
                    **GIANT,
                    "wind_speed": GIANT["wind_speed"] + speed * WIND_SPEED_DRIFT_KMH,
                    "wind_direction": (GIANT["wind_direction"] + bearing * WIND_DIRECTION_DRIFT_DEG)
                    % 360,
                }
            ).significant_wave_height
            - base
        )
        # Both signs of both variables: the coefficients have signs, so only one of the four
        # corners is the worst case and which one it is depends on the bearing.
        for speed in (1, -1)
        for bearing in (1, -1)
    )

    assert moved <= STATED_COST_M, f"{moved:.3f} m exceeds the stated {STATED_COST_M} m — {RERUN}"


def test_the_wind_features_the_bound_covers_are_the_ones_the_model_uses() -> None:
    """The bound above is only a bound if these are still the wind features in the fit.

    A refit adding, say, a gust feature would leave both tests above passing while the
    quantity they reason about had changed underneath them.
    """
    fitted = set(LearnedAmplification().parameters["features"])
    wind = {name for name in fitted if "wind" in name}

    assert wind == {"wind_speed_kmh", "wind_direction_sin", "wind_direction_cos"}, (
        f"the fit's wind features are now {sorted(wind)}, which is not what the shift above "
        f"covers — {RERUN}"
    )
