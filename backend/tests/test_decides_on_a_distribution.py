"""The Decision Model consuming a Predictive Distribution rather than a point estimate.

Ticket #15's seventh criterion, and the second half of its last one: a wider error profile
must produce not just a wider distribution but a more cautious call.

The mechanism is the one ADR 0003 already uses for Model Spread, reached from a third
direction. A Go Call costs money, so it is the tier that has to be sure; a day the system is
not sure about falls to a Watch, because the swell is still worth watching even when it is not
yet worth a flight. Model Spread refuses a Go Call when the forecasters disagree. This refuses
one when the forecast itself is too uncertain to book on.

**A Hindcast passes no distribution, and that is not an oversight.** The three callers in
`analysis/` score the rule against what the ocean actually did, which contains no forecast to
be uncertain about. Scoring must not quietly become stricter than the rule being scored, so a
call decided without a distribution behaves exactly as it did before #15 — asserted below,
because it is what keeps every calibrated bar meaning what it meant when it was fitted.
"""

from __future__ import annotations

from nazarenow.decision import GO_CALL_CONFIDENCE, Agreement, Status, decide
from nazarenow.distribution import ErrorBudget, PredictiveDistribution
from nazarenow.models.learned import LearnedAmplification
from nazarenow.thresholds import load as load_thresholds

MODEL = LearnedAmplification()
BUDGET = ErrorBudget.shipped()
BAR = load_thresholds().minimum_significant_wave_height_m

GIANT = {
    "significant_wave_height": 5.0,
    "swell_height": 4.4,
    "swell_period": 16.0,
    "swell_direction": 300.0,
    "wind_speed": 18.0,
    "wind_direction": 90.0,
}


# The smallest Gold Days on record, as peak Combined Sea in the operational units the running
# system reads. Literals, deliberately, for the reason `test_calls.py` gives about shipped
# bars: importing them would move both sides of the assertion together.
#
# Written by `analysis/forecast_error/confidence.py`, which restates each Gold Day's own
# reanalysis peak through the same Translation `calibrate.py` ships the bars through. The full
# table is `analysis/forecast_error/output/go_call_confidence.csv`; these are the ones that
# bind, the rest sitting from 3.28 m up to 5.99 m.
#
# 2021-11-19 is the one Gold Day below the height bar. It earns no Go Call at any confidence
# because the height condition already refuses it, so it is not this floor's to lose.
SMALLEST_GOLD_DAYS_M = (3.04, 3.04, 3.10, 3.28)
GOLD_DAY_BELOW_THE_BAR_M = 2.11


class TestTheConfidenceFloorCostsNoGoldDay:
    """The budget `GO_CALL_CONFIDENCE` is priced against, in ADR 0010's shape.

    A rule meant to stop somebody booking a flight on a coin flip must not also stop them
    booking one on a day the ocean actually delivered. The floor is therefore the strictest
    value that refuses a Go Call to no Gold Day the height condition admits.

    Pinned here as well as in the analysis because the constant lives in this module and the
    measurement does not. The obvious value, 0.9, would have cost 7 of the 37 eligible Gold
    Days their Go Call — and it looked inert until the probability stopped being read off the
    model's amplified output against a bar that judges the incoming reading.
    """

    def test_every_gold_day_the_height_bar_admits_keeps_its_go_call(self) -> None:
        for peak in SMALLEST_GOLD_DAYS_M:
            for lead in range(1, 8):
                built = BUDGET.distribution(
                    MODEL,
                    GIANT | {"significant_wave_height": peak, "swell_height": round(peak * 0.8, 2)},
                    lead,
                    gold_day_height_m=BAR,
                )

                assert built.gold_day_probability is not None
                assert built.gold_day_probability >= GO_CALL_CONFIDENCE, (
                    f"a {peak} m Gold Day loses its Go Call at {lead} days"
                )

    def test_a_day_sitting_exactly_on_the_bar_is_still_refused(self) -> None:
        """The floor has to keep doing something, or it is a rule priced down to nothing.

        Its active band is the gap between the height bar and the smallest Gold Day — 2.75 m
        to about 3.0 m, where no Gold Day has ever been observed.
        """
        built = BUDGET.distribution(
            MODEL,
            GIANT | {"significant_wave_height": BAR, "swell_height": round(BAR * 0.8, 2)},
            3,
            gold_day_height_m=BAR,
        )

        assert built.gold_day_probability is not None
        assert built.gold_day_probability < GO_CALL_CONFIDENCE

    def test_the_one_gold_day_under_the_bar_is_not_this_rules_to_lose(self) -> None:
        """It fails the height condition outright, so no confidence floor decides it."""
        assert GOLD_DAY_BELOW_THE_BAR_M < BAR


def certainty(probability: float) -> PredictiveDistribution:
    """A distribution of a chosen confidence, built rather than sampled.

    The shipped profile puts a genuine giant day at 1.000 at every Lead Time, which is the
    point of `GO_CALL_CONFIDENCE` — so the marginal cases this rule exists for cannot be
    reached from realistic readings without also changing the sea, and changing the sea
    changes the conditions too. Constructing the distribution isolates the one variable.
    """
    inside = round(probability * 100)
    samples = tuple([BAR + 1.0] * inside + [BAR - 1.0] * (100 - inside))
    return PredictiveDistribution(
        samples=samples, lead_time_days=5, measured=True, gold_day_probability=probability
    )


def call_with(distribution: PredictiveDistribution | None, lead: int = 5):
    return decide(MODEL.predict(GIANT), lead, Agreement.AGREED, distribution)


class TestAHindcastIsUnaffected:
    """Every bar in `thresholds.json` was fitted through this path. It must not move."""

    def test_a_call_without_a_distribution_is_what_it_always_was(self) -> None:
        got = call_with(None)

        assert got.status is Status.GO
        assert got.go_call_withheld_for_uncertainty is False
        assert got.plausible_range_m is None
        assert got.gold_day_probability is None
        assert got.uncertainty_measured is None

    def test_a_distribution_that_never_computed_the_bar_does_not_get_to_veto(self) -> None:
        """`gold_day_probability` is `None` when the builder was not told the height bar.

        Refusing a Go Call on that would be refusing it on a number nobody calculated.
        """
        silent = PredictiveDistribution(
            samples=(5.0, 5.0, 5.0), lead_time_days=5, measured=True, gold_day_probability=None
        )

        assert call_with(silent).status is Status.GO


class TestUncertaintyFallsToAWatch:
    def test_a_confident_distribution_still_earns_a_go_call(self) -> None:
        got = call_with(certainty(1.0))

        assert got.status is Status.GO
        assert got.go_call_withheld_for_uncertainty is False

    def test_an_uncertain_distribution_falls_to_a_watch(self) -> None:
        got = call_with(certainty(0.5))

        assert got.status is Status.WATCH
        assert got.go_call_withheld_for_uncertainty is True

    def test_the_bar_is_inclusive(self) -> None:
        """Checked from both sides at the tightest step, as every other bar in this project
        is, so a comparison written `>` rather than `>=` fails here rather than in a season."""
        assert call_with(certainty(GO_CALL_CONFIDENCE)).status is Status.GO
        assert call_with(certainty(GO_CALL_CONFIDENCE - 0.01)).status is Status.WATCH

    def test_the_reason_says_which_refusal_it_was(self) -> None:
        """Two different facts about the world end in a Watch, and a reader deserves to know
        which: forecasters disagreeing is not the same as one forecast being too uncertain."""
        uncertain = call_with(certainty(0.5))
        divided = decide(MODEL.predict(GIANT), 5, Agreement.DIVIDED, certainty(1.0))

        assert any("too uncertain" in reason for reason in uncertain.reasons)
        assert uncertain.go_call_withheld_for_uncertainty is True
        assert uncertain.go_call_withheld is False

        assert divided.go_call_withheld is True
        assert divided.go_call_withheld_for_uncertainty is False

    def test_uncertainty_cannot_manufacture_a_call_that_was_not_there(self) -> None:
        """A flat day stays nothing. The rule only ever removes a Go Call."""
        flat = GIANT | {"significant_wave_height": 0.5, "swell_period": 6.0}

        got = decide(MODEL.predict(flat), 5, Agreement.AGREED, certainty(1.0))

        assert got.status is Status.NONE


class TestAWiderProfileProducesAMoreCautiousCall:
    """#15's final criterion, second half, end to end through the shipped profile."""

    def test_confidence_falls_as_the_lead_time_grows(self) -> None:
        marginal = GIANT | {"significant_wave_height": 2.8, "swell_height": 2.5}

        near = BUDGET.distribution(MODEL, marginal, 1, gold_day_height_m=BAR)
        far = BUDGET.distribution(MODEL, marginal, 7, gold_day_height_m=BAR)

        assert near.gold_day_probability is not None
        assert far.gold_day_probability is not None
        assert far.gold_day_probability < near.gold_day_probability

    def test_a_genuine_giant_day_keeps_its_go_call_at_every_lead_time(self) -> None:
        """The measurement `GO_CALL_CONFIDENCE` rests on: this floor is inert where it would
        be dangerous. A 5 m sea clears a 2.75 m bar whatever the forecast does, so the rule
        can only ever take a Go Call from the margin.

        Stated as "far clear of the floor" rather than as exactly 1.0. The probability is
        read off the incoming reading's own draws, and at seven days those are 0.72 m wide on
        a big swell — so a handful of the five hundred land under a bar 2.25 m below the
        forecast. That is the distribution being honest, not the floor biting; an assertion
        of exactly 1.0 was only ever true because the figure was previously measured against
        the model's amplified output, where the same day sat further from the bar than the
        reading the bar actually judges.
        """
        for lead in range(2, 8):
            built = BUDGET.distribution(MODEL, GIANT, lead, gold_day_height_m=BAR)

            assert built.gold_day_probability is not None
            assert built.gold_day_probability > GO_CALL_CONFIDENCE + 0.05, f"at {lead} days"
            assert decide(MODEL.predict(GIANT), lead, Agreement.AGREED, built).status is Status.GO


class TestTheCallCarriesTheRange:
    """#15's fourth and fifth criteria reach the interface through `Call`."""

    def test_it_carries_a_range_in_metres_and_a_probability(self) -> None:
        built = BUDGET.distribution(MODEL, GIANT, 3, gold_day_height_m=BAR)

        got = decide(MODEL.predict(GIANT), 3, Agreement.AGREED, built)

        assert got.plausible_range_m is not None
        low, high = got.plausible_range_m
        assert low < got.predicted_significant_wave_height < high
        assert got.gold_day_probability == 1.0

    def test_it_says_whether_the_uncertainty_was_measured(self) -> None:
        inside = BUDGET.distribution(MODEL, GIANT, 7, gold_day_height_m=BAR)
        beyond = BUDGET.distribution(MODEL, GIANT, 9, gold_day_height_m=BAR)

        assert decide(MODEL.predict(GIANT), 7, Agreement.AGREED, inside).uncertainty_measured
        assert (
            decide(MODEL.predict(GIANT), 9, Agreement.AGREED, beyond).uncertainty_measured is False
        )
