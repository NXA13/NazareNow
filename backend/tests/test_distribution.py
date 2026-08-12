"""Building a Predictive Distribution, and the two decisions that shape its width.

Ticket #15, ADR 0004. The system stops answering "6.1 metres" and starts answering "most
likely 6.1 m, plausibly 5.2 to 7.0, and about a one-in-three chance of a genuinely giant
day". Three measured error terms stack between an incoming forecast and that range.

Two choices decide whether the range is honest, and both are asserted here rather than left
to a docstring.

**The centre is corrected before the spread is added.** `drift` in `forecast_error.json` is
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
from nazarenow.spread import ORGANISATIONS, Spread

SEA = "significant_wave_height"

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
        """`drift` is already bias-removed, so the correction moves the centre and must not
        also buy back width. A distribution that narrowed as it corrected would be claiming
        the correction was perfect."""
        got = BUDGET.distribution(MODEL, GIANT, lead_time_days=7)

        assert (got.p95 - got.p5) > 1.0


class TestTheCorrectionHoldsWhereTheMeasurementStops:
    """Past the archive's seven days the width keeps growing and the centre stops moving.

    The two terms are extrapolated differently on purpose, and the reason is the direction
    each one's error points. A frozen *width* would claim uncertainty stops growing at the
    exact day the evidence runs out, which is a false claim of certainty — so it keeps
    growing at the measured rate. A growing *correction* would claim an under-read nobody
    measured, and it moves the centre rather than the edges: the tail rate is -0.092 m a day,
    which reaches -0.87 m by day 14 and would inflate a 5 m sea's centre by 19% on no
    evidence at all, in the one direction that manufactures Go Calls.

    Dropping the correction to zero instead — which is what the first version did — is not
    the cautious middle. It puts a 0.25 m cliff at a fixed calendar boundary: a date crossing
    from eight days out to seven gained a quarter of a metre for methodological rather than
    weather reasons, an order of magnitude above the sampling wobble either side of it, and
    #15's eighth criterion asks a user to read exactly that kind of movement as news.

    So the correction holds at its last measured value. It is the only rule of the three with
    no methodological movement anywhere, it cannot claim more than the archive measured, and
    where it is wrong it under-corrects — which withholds a Go Call rather than inventing one.
    """

    def test_the_centre_does_not_jump_as_a_date_crosses_the_archive_edge(self) -> None:
        seven = BUDGET.distribution(MODEL, GIANT, lead_time_days=7)
        eight = BUDGET.distribution(MODEL, GIANT, lead_time_days=8)

        assert abs(eight.median - seven.median) < 0.1

    def test_the_centre_stops_moving_once_nothing_more_is_measured(self) -> None:
        """Flat beyond the edge, so every median change a user sees out there is weather."""
        seven = BUDGET.distribution(MODEL, GIANT, lead_time_days=7)

        for lead in (8, 10, 14):
            beyond = BUDGET.distribution(MODEL, GIANT, lead_time_days=lead)
            assert abs(beyond.median - seven.median) < 0.1, f"the centre moved at {lead} days"

    def test_holding_the_correction_is_visibly_not_extrapolating_it(self) -> None:
        """The bound that rules out the third option, stated against that option.

        The archive's last two Lead Times fall 0.092 m a day, so continuing the trend would
        reach roughly 0.64 m of extra correction by day 14 — larger than the correction ever
        measured, and applied to the centre. Measured off the profile rather than hardcoded,
        so the test still describes the choice if the profile is re-measured.
        """
        seventh, sixth = BUDGET.forecast.at(7), BUDGET.forecast.at(6)
        assert seventh is not None and sixth is not None
        per_day = abs(seventh.for_sea(5.0).bias - sixth.for_sea(5.0).bias)
        seven_days_of_trend = per_day * 7
        assert seven_days_of_trend > 0.5, "the trend is steep enough for this to be a real choice"

        at_the_edge = BUDGET.distribution(MODEL, GIANT, lead_time_days=7).median
        far_out = BUDGET.distribution(MODEL, GIANT, lead_time_days=14).median

        assert far_out - at_the_edge < seven_days_of_trend / 4

    def test_the_width_still_grows_out_there(self) -> None:
        assert spread_at(8) < spread_at(10) < spread_at(14)


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
        input_sigma = (drift.for_sea(5.0).drift ** 2 + BUDGET.translation_rmse**2) ** 0.5
        unamplified = 3.29 * (input_sigma**2 + BUDGET.own_error(5.0) ** 2) ** 0.5

        assert spread_at(7) > unamplified

    def test_the_bigger_sea_reads_the_bigger_regime(self) -> None:
        """Both the drift band and the model's own residual are regime-split at 3 m, and
        conditioning on the regime is what makes combining them defensible."""
        big = GIANT | {"significant_wave_height": 6.0, "swell_height": 5.5}
        small = GIANT | {"significant_wave_height": 1.2, "swell_height": 1.0}

        assert spread_at(7, big) > spread_at(7, small)


def disagreement(metres: float, providers: int = 3, variable: str = SEA) -> Spread:
    """A Model Spread of a given width, in the shape `spread.derive` returns."""
    return Spread(
        variable=variable,
        value=metres,
        lowest=5.0 - metres / 2,
        highest=5.0 + metres / 2,
        providers=tuple(ORGANISATIONS[:providers]),
        models_reporting=providers,
    )


class TestModelSpreadWidensTheSameDistribution:
    """#15's third criterion: one distribution, not two numbers reported side by side.

    Model Spread already withheld a Go Call through `Agreement`, which is a gate rather than
    a width — the range a user read was the same whether the forecasters agreed or not. Here
    the same disagreement enters the range itself.

    **The archive's drift is a floor the ensemble can raise and never lower.** The two are
    not added, because they measure overlapping things and this module claims independence
    only where it is earned. They are not interchangeable either: the archive measures one
    provider's own change of mind against its settled analysis, which cannot see an error
    that provider is consistently wrong about, while the ensemble measures where
    organisations differ, which cannot see an error they share. Neither bounds the other, so
    the larger of the two is the honest "at least this uncertain".

    Both terms really do bind. Against `analysis/model_spread/output/alignment.csv`, the
    0.446 m provider range at one day is 0.263 m of sigma against 0.130 m of big-swell
    drift, so the ensemble carries it; by six days the drift is 0.606 m against the
    ensemble's 0.385 m and the archive carries it. A rule where one side never bound would
    be a rule with one term.

    That it may only raise is the same asymmetry `spread.py` ships on. Three deterministic
    models sharing physics are under-dispersed, so the ensemble sigma understates; run
    staleness inflates it by 6% at one day and up to 29% at six, so it also overstates. Both
    errors are survivable in a term that can only widen, and neither is survivable in one
    that could narrow.
    """

    def test_a_day_the_forecasters_divide_over_gets_a_wider_range(self) -> None:
        agreed = BUDGET.distribution(MODEL, GIANT, 3, model_spread=disagreement(0.2))
        divided = BUDGET.distribution(MODEL, GIANT, 3, model_spread=disagreement(2.0))

        assert (divided.p95 - divided.p5) > (agreed.p95 - agreed.p5)

    def test_close_agreement_cannot_narrow_the_measured_drift(self) -> None:
        """The floor. Agreement is not evidence of correctness — three models can agree
        precisely and be wrong together, which is the failure the archive term measures and
        the ensemble term structurally cannot see."""
        alone = BUDGET.distribution(MODEL, GIANT, 7)
        unanimous = BUDGET.distribution(MODEL, GIANT, 7, model_spread=disagreement(0.001))

        assert unanimous.samples == alone.samples

    def test_no_ensemble_at_all_leaves_the_distribution_exactly_as_it_was(self) -> None:
        """An unreachable ensemble degrades the estimate rather than the prediction (ADR
        0003), and a Hindcast has no ensemble to consult at all. Asserted on the samples
        rather than the width, so this cannot pass by being merely close."""
        assert (
            BUDGET.distribution(MODEL, GIANT, 5, model_spread=None).samples
            == BUDGET.distribution(MODEL, GIANT, 5).samples
        )

    def test_two_organisations_imply_a_wider_sigma_than_three_at_the_same_range(self) -> None:
        """The range of three samples is expected to be wider than the range of two, so the
        same measured range means more disagreement when fewer reported it. Ignoring the
        count would read a degraded ensemble as a calmer one."""
        two = BUDGET.distribution(MODEL, GIANT, 3, model_spread=disagreement(2.0, providers=2))
        three = BUDGET.distribution(MODEL, GIANT, 3, model_spread=disagreement(2.0, providers=3))

        assert (two.p95 - two.p5) > (three.p95 - three.p5)

    def test_a_spread_on_the_wrong_quantity_is_refused(self) -> None:
        """CONTEXT.md's load-bearing distinction, guarded at the seam. A swell-period spread
        is a number of seconds; widening a distribution of metres by it would produce a
        confident-looking range nobody could detect as wrong."""
        with pytest.raises(ValueError, match="swell_period"):
            BUDGET.distribution(
                MODEL, GIANT, 3, model_spread=disagreement(2.0, variable="swell_period")
            )


class TestTheHeightBarProbabilityIsAboutTheBarThatIsActuallyJudged:
    """#15's fifth criterion, and the quantity trap sitting under it.

    The calibrated height bar is fitted in operational Open-Meteo units and applied by the
    Amplification Model to the **incoming Combined Sea reading** — `heuristic.predict` reads
    `readings["significant_wave_height"]` and compares it, and every tier branch in `decide`
    rests on that verdict. The distribution's samples are the model's **output**, the Proxy
    Target at Monican02, which the model amplifies to from that same reading.

    Measuring the output against an input-side bar asks a different question from the one
    the tier asks, and it flatters by exactly the amplification: a 2.75 m sea sitting on the
    bar leaves the model at 3.15 m, so it reads 0.84 where the comparison warrants 0.50. The
    bar already embeds whatever amplification exists between a reading and a Gold Day —
    that is what fitting it against Gold Days *means* — so applying it again downstream
    counts the canyon twice.

    CONTEXT.md's Go Call entry is the wording this follows: "predicted conditions clear the
    Gold Day threshold", where the conditions are the ones the model judges.
    """

    def test_a_sea_sitting_exactly_on_the_bar_is_a_coin_flip(self) -> None:
        """The measurement that shows the quantity is right. A forecast reading exactly the
        bar has half its plausible values either side of it, whatever the canyon does
        downstream — and a Go Call costs a flight."""
        on_the_bar = GIANT | {"significant_wave_height": 2.75, "swell_height": 2.2}

        got = BUDGET.distribution(MODEL, on_the_bar, 3, height_bar_m=2.75)

        assert got.height_bar_probability is not None
        assert 0.4 < got.height_bar_probability < 0.6

    def test_a_genuine_giant_clears_it_at_every_lead_time(self) -> None:
        """The inertness `GO_CALL_MINIMUM_HEIGHT_PROBABILITY` is documented to have, on the
        corrected quantity. A 5 m sea clears a 2.75 m bar whatever the forecast does, so this
        floor cannot take a Go Call from a day anyone would fly for."""
        for lead in (1, 3, 7):
            got = BUDGET.distribution(MODEL, GIANT, lead, height_bar_m=2.75)
            assert got.height_bar_probability == pytest.approx(1.0, abs=0.02), f"at {lead} days"

    def test_the_range_a_user_reads_is_still_the_predicted_sea(self) -> None:
        """The two quantities stay apart rather than one replacing the other. The range
        answers "how big will it be" and is the model's output; the probability answers
        "does it clear the bar" and is the reading the bar judges."""
        got = BUDGET.distribution(MODEL, GIANT, 3, height_bar_m=2.75)

        assert got.p5 < MODEL.predict(GIANT).significant_wave_height < got.p95


class TestTheProbabilityOfClearingTheHeightBar:
    """#15's fifth criterion, as far as it can be met: the chance of clearing the height bar.

    The criterion asked for the chance of reaching Gold Day *conditions*, plural. Three of the
    four cannot be given a probability — the Swell partition is unarchived and wind is not
    perturbed — so what is asserted here is the one condition that can be, and #66 renamed the
    field and the interface copy to stop the number reading as all four. ADR 0004's #66
    amendment carries the reasoning.
    """

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
