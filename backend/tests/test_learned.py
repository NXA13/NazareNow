"""The learned Amplification Model: what the swap may change, and what it may not.

Ticket #13. ADR 0006 keeps the Heuristic Baseline permanently and requires the two be
swappable behind one interface, so these tests are mostly about the *boundary* rather than
about accuracy. No figure here asserts how good the model is — #11 established why an
accuracy assertion in the suite gets disabled within weeks, and `analysis/amplification_model/`
is where the numbers live.

What is pinned instead is the pair of claims the swap rests on:

1. **It changes the number and nothing else.** The Decision Model branches on `Condition`
   identities (`decision.py`), and the learned model delegates every one of them to the real
   `HeuristicBaseline`. So swapping the model cannot silently re-tier a day. That is not a
   stylistic preference: the shipped `minimum_significant_wave_height_m` was fitted against
   *offshore Open-Meteo wave height*, and the learned model emits a predicted Proxy Target —
   a different quantity. Judging the new number against the old bar would be exactly the
   units conflation CLAUDE.md calls load-bearing.

2. **It is fed what it was fitted on.** The fit is on the Copernicus IBI reanalysis and the
   Pipeline Run consumes Open-Meteo, which reads about half a second short on swell period
   with a compressed range (`analysis/overlap/README.md`). The translation is applied on the
   way in, and a model that quietly stopped applying it would still return plausible numbers.
"""

from __future__ import annotations

import json
import math

import pytest

from nazarenow.models.base import AmplificationModel, Condition
from nazarenow.models.heuristic import HeuristicBaseline
from nazarenow.models.learned import PARAMETERS_PATH, LearnedAmplification, load_parameters

GIANT = {
    "significant_wave_height": 5.0,
    "swell_height": 4.4,
    "swell_period": 16.0,
    "swell_direction": 300.0,
    "wind_speed": 18.0,
    "wind_direction": 90.0,
}

# A deliberately trivial parameter set: one feature, unit slope, no intercept, and
# translations that are the identity. Built by hand so a test can predict the arithmetic
# exactly, which the shipped file's nine-decimal coefficients do not allow.
PLAIN = {
    "model": "learned-amplification",
    "features": ["combined_sea_m"],
    "intercept": 0.0,
    "coefficients": [1.0],
    "translations": {
        "significant_wave_height_m": {"slope": 1.0, "intercept": 0.0},
        "swell_period_s": {"slope": 1.0, "intercept": 0.0},
    },
}


def parameters(**changes: object) -> dict:
    return {**PLAIN, **changes}


class TestTheSwapChangesTheNumberAndNothingElse:
    def test_every_condition_matches_the_baseline_exactly(self) -> None:
        """The verdicts the Decision Model reads, delegated rather than reimplemented.

        Compared as whole `ConditionOutcome`s, not just their identities: the explanations
        are what the user reads, and a learned model that reworded them would change the
        interface's copy without anyone deciding to.
        """
        learned = LearnedAmplification(parameters=parameters()).predict(GIANT)
        baseline = HeuristicBaseline().predict(GIANT)

        assert learned.conditions == baseline.conditions

    @pytest.mark.parametrize(
        "change",
        [
            {"swell_period": 10.0},
            {"swell_direction": 254.0},
            {"wind_speed": 40.0},
            {"significant_wave_height": 0.5},
        ],
    )
    def test_a_day_the_baseline_refuses_is_refused_identically(self, change: dict) -> None:
        """Including on height — the one condition the learned model might be thought to own.

        It does not own it. The height *condition* stays a statement about the offshore
        forecast against a bar fitted in offshore units; only the emitted prediction is the
        model's own.
        """
        readings = GIANT | change
        learned = LearnedAmplification(parameters=parameters()).predict(readings)
        baseline = HeuristicBaseline().predict(readings)

        assert learned.matches_rule == baseline.matches_rule
        assert learned.unmatched == baseline.unmatched

    def test_it_earns_a_number_distinct_from_its_input(self) -> None:
        """The criterion carried from #6, at the level this class can hold it.

        The baseline returns its own input by construction; the learned model must not. The
        coefficients here make it arithmetically certain rather than data-dependent, so this
        stays a statement about the class and not about a particular fit.
        """
        model = LearnedAmplification(parameters=parameters(intercept=0.5, coefficients=[1.2]))

        prediction = model.predict(GIANT)

        assert prediction.significant_wave_height == pytest.approx(0.5 + 1.2 * 5.0)
        assert prediction.significant_wave_height != GIANT["significant_wave_height"]
        assert prediction.unit == "m"


class TestItIsFedWhatItWasFittedOn:
    def test_the_translation_is_applied_before_the_coefficients(self) -> None:
        """Operational readings are restated in reanalysis units on the way in.

        `Translation` is fitted as `operational = slope x reanalysis + intercept`, so the
        model — which lives in reanalysis units — needs the inverse. With slope 0.5 and
        intercept 1.0, an operational 5.0 m is a reanalysis 8.0 m, and a unit coefficient
        must therefore predict 8.0 rather than 5.0.
        """
        model = LearnedAmplification(
            parameters=parameters(
                translations={
                    "significant_wave_height_m": {"slope": 0.5, "intercept": 1.0},
                    "swell_period_s": {"slope": 1.0, "intercept": 0.0},
                }
            )
        )

        prediction = model.predict(GIANT)

        assert prediction.significant_wave_height == pytest.approx(8.0)

    def test_a_missing_translation_is_refused_rather_than_skipped(self) -> None:
        """Skipping it silently would feed operational numbers to reanalysis coefficients.

        The result would be wrong by about the size of the offset and entirely plausible,
        which is the failure mode this project is built to refuse.
        """
        broken = parameters(translations={"swell_period_s": {"slope": 1.0, "intercept": 0.0}})

        with pytest.raises(ValueError, match="significant_wave_height_m"):
            LearnedAmplification(parameters=broken).predict(GIANT)


class TestTheFeatureVector:
    def test_an_unknown_feature_is_refused_rather_than_treated_as_zero(self) -> None:
        """A parameter file naming a column this code cannot build is a version mismatch.

        Defaulting it to zero would drop a term from the fit and keep predicting — quietly
        returning a model nobody trained.
        """
        with pytest.raises(ValueError, match="wave_steepness"):
            LearnedAmplification(
                parameters=parameters(features=["wave_steepness"], coefficients=[1.0])
            ).predict(GIANT)

    def test_features_and_coefficients_must_be_the_same_length(self) -> None:
        with pytest.raises(ValueError, match="coefficient"):
            LearnedAmplification(
                parameters=parameters(features=["combined_sea_m", "swell_period_s"])
            ).predict(GIANT)

    def test_bearings_are_encoded_so_north_is_not_a_discontinuity(self) -> None:
        """359 degrees and 1 degree are two degrees apart, not 358.

        A linear term on raw degrees says otherwise, and would put a cliff at north in the
        middle of the swell arc's neighbourhood. The sine/cosine pair is what makes the two
        bearings behave like the neighbours they are.
        """
        model = LearnedAmplification(
            parameters=parameters(
                features=["swell_direction_sin", "swell_direction_cos"],
                coefficients=[1.0, 1.0],
            )
        )

        just_east = model.predict(GIANT | {"swell_direction": 1.0}).significant_wave_height
        just_west = model.predict(GIANT | {"swell_direction": 359.0}).significant_wave_height

        assert just_east == pytest.approx(just_west, abs=0.05)

    def test_the_interaction_is_the_product_of_its_two_terms(self) -> None:
        model = LearnedAmplification(
            parameters=parameters(features=["combined_sea_x_period"], coefficients=[1.0])
        )

        prediction = model.predict(GIANT)

        assert prediction.significant_wave_height == pytest.approx(5.0 * 16.0)


class TestItRefusesToEmitAnImpossibleSea:
    def test_a_negative_prediction_is_floored_at_zero(self) -> None:
        """A line fitted on 2-6 m seas has no obligation to stay positive at 0.2 m.

        Extrapolated far below its fitting range it can cross zero, and a negative
        Significant Wave Height is not a cautious prediction — it is a number with no
        physical reading that would flow into the store and onto the page.
        """
        model = LearnedAmplification(parameters=parameters(intercept=-50.0))

        prediction = model.predict(GIANT)

        assert prediction.significant_wave_height == 0.0


class TestTheShippedParameterFile:
    def test_it_exists_and_every_feature_it_names_can_be_built(self) -> None:
        """The file `analysis/amplification_model/train.py` writes, read the way the
        Pipeline Run reads it. A file naming a feature the backend cannot build would fail
        only when a run happened to execute."""
        assert PARAMETERS_PATH.exists()

        prediction = LearnedAmplification().predict(GIANT)

        assert prediction.significant_wave_height > 0.0
        assert math.isfinite(prediction.significant_wave_height)

    def test_it_carries_the_provenance_of_its_fit(self) -> None:
        """Same obligation `thresholds.json` carries under #12: a reader must be able to see
        what the numbers rest on without going to the analysis module."""
        loaded = json.loads(PARAMETERS_PATH.read_text(encoding="utf-8"))
        method = loaded["method"]

        assert method["ticket"] == 13
        assert method["fitted_on"] != method["held_out"]
        assert method["rows_fitted"] > 0
        assert "not_amplification" in method

    def test_load_parameters_is_what_the_model_defaults_to(self) -> None:
        assert LearnedAmplification().parameters == load_parameters()


def test_it_satisfies_the_amplification_model_interface() -> None:
    """The Protocol, checked structurally rather than by inheritance.

    `pipeline.amplification_model` is annotated as returning `AmplificationModel`, so the
    type checker already proves this statically. Asserting it here as well is what catches
    the runtime half — a `predict` that returns something other than a `Prediction`.
    """
    model: AmplificationModel = LearnedAmplification()

    assert model.name == "learned-amplification"
    assert isinstance(model.calibrated, bool)

    prediction = model.predict(GIANT)

    assert prediction.holds(Condition.SIGNIFICANT_WAVE_HEIGHT)
    assert isinstance(prediction.matched, tuple)


def test_it_reports_the_calibration_its_conditions_actually_rest_on() -> None:
    """Its verdicts are the baseline's, so its `calibrated` flag is the baseline's too.

    Read through to the threshold set rather than asserted, for the reason `heuristic.py`
    gives: a model that could set this itself could claim a calibration its numbers do not
    have. `pipeline.calibration_of` reads `.thresholds` off the model, and the learned model
    exposes the same set precisely because those thresholds really did judge the conditions.
    """
    model = LearnedAmplification()

    assert model.calibrated is HeuristicBaseline().calibrated
    assert model.thresholds == HeuristicBaseline().thresholds


def test_the_same_readings_always_give_the_same_answer() -> None:
    """Deterministic, which is what lets #15 perturb inputs and read the spread as signal."""
    model = LearnedAmplification()

    assert model.predict(GIANT) == model.predict(dict(GIANT))
