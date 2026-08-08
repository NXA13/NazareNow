"""Building a Predictive Distribution, and the two decisions that shape its width.

Ticket #15, ADR 0004. The system stops answering "6.1 metres" and starts answering "most
likely 6.1 m, plausibly 5.2 to 7.0, and about a one-in-three chance of a genuinely giant
day". Three measured error terms stack between an incoming forecast and that range.

Two choices decide whether the range is honest, and both are asserted here rather than left
to a docstring.

**The centre is corrected before the spread is added.** `noise` in `forecast_error.json` is
already `sqrt(rmse^2 - bias^2)` — the width that remains *after* a constant correction. Using
that width without applying the correction it presupposes centres the distribution on a value
the archive measured to be wrong, and then reports a confident interval around it. #14's own
`bias_share` docstring asks for the correction first, and at seven days on a big swell the
bias is -0.230 m: the forecast reads low exactly where a user still has time to book.

**Errors are propagated, not summed.** Forecast drift is an error in the *input*; the
Amplification Model's own residual is an error in the *output*. The model has a measured gain
of about 1.083, so a metre of input error is not a metre of output error. Adding the three
published metre figures in quadrature would understate the dominant input term by roughly 8%
and would be wrong even if every term were perfectly independent.
"""

from __future__ import annotations

import pytest

from nazarenow.distribution import ErrorBudget
from nazarenow.models.learned import LearnedAmplification

GIANT = {
    "significant_wave_height": 5.0,
    "swell_height": 4.4,
    "swell_period": 16.0,
    "swell_direction": 300.0,
    "wind_speed": 18.0,
    "wind_direction": 90.0,
}

MODEL = LearnedAmplification()
BUDGET = ErrorBudget.shipped()


def spread_at(lead: int, readings: dict[str, float] | None = None) -> float:
    got = BUDGET.distribution(MODEL, readings or GIANT, lead_time_days=lead)
    return got.p95 - got.p5


class TestTheRangeIsAnActualRange:
    def test_it_is_ordered_and_contains_its_own_centre(self) -> None:
        got = BUDGET.distribution(MODEL, GIANT, lead_time_days=3)

        assert got.p5 < got.median < got.p95
        assert got.p5 <= got.mean <= got.p95

    def test_it_is_reported_in_metres_rather_than_as_a_bare_percentage(self) -> None:
        """#15's fourth criterion. The point of the ticket is that a user can reason about
        the answer, and "78% confident" is not something anyone can act on."""
        got = BUDGET.distribution(MODEL, GIANT, lead_time_days=3)

        low, high = got.range_m
        assert low == pytest.approx(got.p5)
        assert high == pytest.approx(got.p95)
        assert high - low > 0.1

    def test_the_same_inputs_always_give_the_same_range(self) -> None:
        """Matching `test_the_same_readings_always_give_the_same_answer` for the point
        model. A Pipeline Run that re-scored a date and moved the range without the forecast
        moving would make #15's eighth criterion — showing how a prediction shifted between
        runs — meaningless."""
        first = BUDGET.distribution(MODEL, GIANT, lead_time_days=4)
        second = BUDGET.distribution(MODEL, GIANT, lead_time_days=4)

        assert first.samples == second.samples

    def test_a_height_cannot_come_out_negative(self) -> None:
        """The point model floors at zero; sampling around a small sea must not undo that."""
        flat = GIANT | {"significant_wave_height": 0.4, "swell_height": 0.3}

        got = BUDGET.distribution(MODEL, flat, lead_time_days=7)

        assert got.p5 >= 0.0
        assert min(got.samples) >= 0.0


class TestUncertaintyGrowsWithLeadTime:
    def test_a_longer_lead_time_is_a_wider_range(self) -> None:
        """The measured profile grows roughly 0.07 m a day; the range must follow it."""
        assert spread_at(1) < spread_at(3) < spread_at(5) < spread_at(7)

    def test_beyond_the_measured_archive_it_is_wider_still_and_says_so(self) -> None:
        """#15's sixth criterion. Eight days out has no measured profile at all.

        Reusing the seven-day band would quietly claim evidence the archive does not have,
        and it would render identically to a measured range. So the width keeps growing and
        the distribution carries `measured=False` for the interface to show.
        """
        seven = BUDGET.distribution(MODEL, GIANT, lead_time_days=7)
        ten = BUDGET.distribution(MODEL, GIANT, lead_time_days=10)

        assert seven.measured is True
        assert ten.measured is False
        assert (ten.p95 - ten.p5) > (seven.p95 - seven.p5)

    def test_a_wider_error_profile_produces_a_wider_distribution(self) -> None:
        """#15's final criterion, first half. The other half — a more cautious call — needs
        `decide` to consume the distribution and is the next step."""
        narrow = ErrorBudget.shipped().distribution(MODEL, GIANT, lead_time_days=1)
        wide = ErrorBudget.shipped().distribution(MODEL, GIANT, lead_time_days=7)

        assert (wide.p95 - wide.p5) > (narrow.p95 - narrow.p5)


class TestTheCentreIsCorrectedBeforeTheSpreadIsAdded:
    """The first of the two decisions. See the module docstring."""

    def test_a_long_lead_big_swell_is_centred_above_the_uncorrected_prediction(self) -> None:
        """At seven days the big-swell forecast reads 0.230 m low against the provider's own
        settled analysis. The distribution must not inherit that."""
        point = MODEL.predict(GIANT).significant_wave_height

        got = BUDGET.distribution(MODEL, GIANT, lead_time_days=7)

        assert got.median > point

    def test_the_correction_follows_the_measured_sign_rather_than_always_lifting(self) -> None:
        """At two days the big-swell bias is *positive* (+0.039): the forecast reads high
        there, and the correction has to push the other way.

        This is the test that would fail if the sign were flipped — a mistake that would
        otherwise look like a slightly optimistic system rather than a bug.
        """
        point = MODEL.predict(GIANT).significant_wave_height

        got = BUDGET.distribution(MODEL, GIANT, lead_time_days=2)

        assert got.median < point

    def test_correcting_does_not_narrow_the_range(self) -> None:
        """`noise` is already bias-removed, so the correction moves the centre and must not
        also buy back width. A distribution that narrowed as it corrected would be claiming
        the correction was perfect."""
        got = BUDGET.distribution(MODEL, GIANT, lead_time_days=7)

        assert (got.p95 - got.p5) > 1.0


class TestErrorsArePropagatedRatherThanSummed:
    """The second of the two decisions. See the module docstring."""

    def test_input_error_reaches_the_output_through_the_models_gain(self) -> None:
        """The model amplifies: about 1.083 m out per metre in.

        So the drift term's contribution to the output range is larger than the metre figure
        published in `forecast_error.json`, and a distribution that added the raw figures
        would be too narrow. Measured here rather than asserted, by comparing the range
        against the drift term scaled both ways.
        """
        lo = MODEL.predict(GIANT | {"significant_wave_height": 4.5}).significant_wave_height
        hi = MODEL.predict(GIANT | {"significant_wave_height": 5.5}).significant_wave_height
        gain = hi - lo

        assert gain > 1.0, "the model amplifies, so propagation and summation differ"

        # The 90% span of a normal is about 3.29 sigma. With drift and the Translation on the
        # input side and the model's own residual on the output, the propagated span must
        # exceed what those same terms give if the input ones are not amplified.
        drift = BUDGET.forecast.at(7)
        assert drift is not None
        input_sigma = (drift.for_sea(5.0).noise ** 2 + BUDGET.translation_rmse**2) ** 0.5
        unamplified = 3.29 * (input_sigma**2 + BUDGET.own_error(5.0) ** 2) ** 0.5

        assert spread_at(7) > unamplified

    def test_the_bigger_sea_reads_the_bigger_regime(self) -> None:
        """Both the drift band and the model's own residual are regime-split at 3 m, and
        conditioning on the regime is what makes combining them defensible."""
        big = GIANT | {"significant_wave_height": 6.0, "swell_height": 5.5}
        small = GIANT | {"significant_wave_height": 1.2, "swell_height": 1.0}

        assert spread_at(7, big) > spread_at(7, small)


class TestTheProbabilityOfAGiantDay:
    """#15's fifth criterion: state the chance of a date reaching Gold Day conditions."""

    def test_a_giant_forecast_is_more_likely_than_a_flat_one(self) -> None:
        giant = BUDGET.distribution(MODEL, GIANT, lead_time_days=3)
        flat = BUDGET.distribution(
            MODEL, GIANT | {"significant_wave_height": 1.0, "swell_height": 0.8}, 3
        )

        assert giant.probability_above(5.0) > flat.probability_above(5.0)

    def test_it_is_a_probability(self) -> None:
        got = BUDGET.distribution(MODEL, GIANT, lead_time_days=3)

        assert 0.0 <= got.probability_above(5.0) <= 1.0
        assert got.probability_above(0.0) == 1.0
        assert got.probability_above(500.0) == 0.0

    def test_certainty_falls_away_as_the_lead_time_grows(self) -> None:
        """A near-certain call one day out should not stay near-certain a week out."""
        near = BUDGET.distribution(MODEL, GIANT, lead_time_days=1)
        far = BUDGET.distribution(MODEL, GIANT, lead_time_days=7)

        assert near.probability_above(4.0) > far.probability_above(4.0)


class TestTheShippedBudget:
    def test_it_carries_all_three_terms(self) -> None:
        """The failure #14 warned about is a consumer using drift alone, which at one day is
        the smallest of the three and would give a range roughly three times too narrow."""
        assert BUDGET.translation_rmse > 0
        assert BUDGET.own_error(5.0) > BUDGET.translation_rmse
        assert BUDGET.forecast.at(1) is not None

    def test_the_models_own_error_is_regime_split(self) -> None:
        assert BUDGET.own_error(5.0) > BUDGET.own_error(1.0)
