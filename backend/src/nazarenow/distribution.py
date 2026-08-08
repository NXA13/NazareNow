"""A Predictive Distribution: what the system thinks, and how sure it is entitled to be.

Ticket #15, ADR 0004. The Amplification Model returns one number. Three measured error terms
sit between an incoming forecast and any honest statement about a date, and this module
stacks them into a range a person can act on.

    forecast drift            forecast_error.json, `noise`, per Lead Time and regime
    the Translation residual  amplification.json, `translations.*.residual_rmse`
    the model's own error     amplification.json, `residual.*.rmse`

**Where each term enters is not a detail.** The first two are errors in the *input* — how
wrong the incoming Combined Sea reading is, and how wrong its restatement into Hindcast units
is. The third is an error in the *output*, being the residual of a fit given true inputs. The
model amplifies, at a measured gain of about 1.083 m out per metre in, so input error reaches
the user larger than it started. Adding the three published metre figures in quadrature would
understate the dominant term by roughly 8% and would be wrong even if the terms were perfectly
independent, which is why this samples and propagates rather than summing.

Independence is claimed only where it is earned. The two input terms are different quantities
— one is Open-Meteo revising its own forecast, the other is the Open-Meteo-to-IBI mapping —
so combining them at the input is reasonable. The model's residual is by construction the part
of the target its inputs do not explain, which is the standard regression assumption and the
right one here. Both drift and the model's error grow with the sea, and that shared driver is
handled by conditioning: every term is read at the regime the reading falls in, so the
correlation that would otherwise couple them has largely been taken out before they meet.

**The centre is corrected before the spread is added.** `noise` is already
`sqrt(rmse^2 - bias^2)`: the width that survives a constant correction. Using it without
applying that correction centres the range on a value the archive measured to be wrong and
then draws a confident interval around it — #14's `bias_share` docstring asks for the
correction first, in those words. At seven days on a big swell the bias is -0.230 m, so the
uncorrected centre sits low exactly where a user still has time to book a flight.

The correction is applied at every measured Lead Time rather than above some significance
cutoff. A cutoff would be one more parameter fitted on a single Big-Wave Season, and the short
Lead Time biases are small enough (0.5% to 7% of the combined width) that applying them is
nearly a no-op. One rule, statable in a sentence, beats a threshold nobody can defend.

**Beyond the archive, the width keeps growing and the centre stops moving.** The wave run
archive reaches seven days. Past that the width continues at the growth rate the archive
measured and the distribution is marked `measured=False`, so the interface can be visibly more
cautious rather than quietly reusing the last band it had. The correction holds at its last
measured value instead of growing or vanishing — `_unmeasured_drift` carries the reasoning,
and the short version is that widening errs toward caution while moving a centre does not.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, replace
from typing import Any

from nazarenow.forecast_error import ForecastError
from nazarenow.forecast_error import load as load_forecast_error
from nazarenow.models.base import AmplificationModel
from nazarenow.models.learned import load_parameters
from nazarenow.spread import Spread

SEA = "significant_wave_height"
"""The one quantity a Model Spread may widen this distribution by.

Named because the check that enforces it is the guard on CONTEXT.md's load-bearing
distinction: a swell-period spread is a number of seconds, and widening a distribution of
metres by it would produce a confident-looking range nothing downstream could detect as wrong.
"""

RANGE_TO_SIGMA = {2: 1.128, 3: 1.693}
"""Expected range of *n* standard normal samples, in sigma — the control-chart `d2` constants.

Model Spread is published as a range across organisations (`spread.spread_of`), and the terms
it is being combined with are standard deviations. Dividing by the count's own factor is what
makes them the same kind of number. It matters which count: the same 0.5 m range means more
disagreement from two organisations than from three, so ignoring the count would read a
degraded ensemble as a calmer one, at exactly the Lead Times where members drop out.

Keyed on the organisation counts this roster can produce — `spread.MINIMUM_PROVIDERS` is two
and `spread.ORGANISATIONS` has three. A count outside the table contributes no ensemble term
rather than guessing a factor, so a roster that grows loses this widening until the table is
extended, and never invents a width for it.
"""

DRAWS = 500
"""Evaluations per date.

`analysis/amplification_model/output/inference_cost.csv` measures the point model at tens of
microseconds, and #15's modelled shape is 500 draws across a 14-day range — well inside a
forecast cycle, which is the ticket's ninth criterion.
"""

SEED = 15
"""Fixed, so a date re-scored without its forecast moving returns the same range.

#15 asks the interface to show how a prediction shifted between Pipeline Runs. A range that
wobbled on its own would make that display meaningless — the user could not tell a changed
forecast from a reshuffled sample.
"""

SPAN_90 = 3.2897072539029457
"""Width of a standard normal's 5th-to-95th percentile span, in sigma. Used only to reason
about widths in tests and comments, never to replace the sampled percentiles."""


@dataclass(frozen=True)
class PredictiveDistribution:
    """What the system thinks a date will bring, as a spread rather than a point."""

    samples: tuple[float, ...]
    """The model's output: the predicted sea, in the unit the call reports. The range."""

    lead_time_days: int
    measured: bool
    """Whether a Forecast Error Profile actually covered this Lead Time.

    `False` past the archive's seven days. The width is still honest — it keeps growing at the
    measured rate — but nothing was measured about it, and the interface has to be able to say
    so rather than presenting an extrapolation as evidence.
    """

    offshore_samples: tuple[float, ...] = ()
    """The same draws on the *input* side: the perturbed incoming Combined Sea reading.

    Kept because the calibrated height bar is a bar on this quantity, not on `samples`. See
    `gold_day_probability`, which is the only thing that reads it.
    """

    gold_day_probability: float | None = None
    """The share of the incoming reading's draws clearing the calibrated height bar.

    Attached here rather than computed by `decide`, because the bar lives in `thresholds.json`
    and a `Prediction` arrives with its conditions already evaluated — the Decision Model never
    sees a threshold, and giving it one to satisfy this would invert that. `None` when the
    builder was not told the bar, which is the Hindcast case.

    **Read off `offshore_samples` rather than `samples`, and the difference is not cosmetic.**
    The bar is fitted in operational Open-Meteo units and applied by the model to the incoming
    Combined Sea — `heuristic.predict` compares `readings["significant_wave_height"]` against
    it, and every tier branch in `decide` rests on that verdict. `samples` are the model's
    output, the Proxy Target at Monican02, which the model amplifies to from that same reading.

    Measuring the output against an input-side bar therefore asks a different question from
    the one the tier asks, and it flatters by exactly the amplification: a 2.75 m sea sitting
    on the bar leaves the model at 3.15 m and reads 0.84 where the comparison warrants 0.50.
    The bar already embeds whatever amplification stands between a reading and a Gold Day —
    that is what fitting it against Gold Days means — so applying it downstream counts the
    canyon twice, on the one condition thresholds.json records as "verified to block no Gold
    Day rather than fitted".
    """

    @property
    def median(self) -> float:
        return statistics.median(self.samples)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples)

    @property
    def p5(self) -> float:
        return self._percentile(0.05)

    @property
    def p95(self) -> float:
        return self._percentile(0.95)

    @property
    def range_m(self) -> tuple[float, float]:
        """The plausible range in metres, which is what #15 asks the user be shown."""
        return self.p5, self.p95

    def probability_above(self, metres: float) -> float:
        """The share of the predicted sea clearing a height — "how likely is it this big".

        Read off the samples rather than a fitted normal, because the samples carry the
        model's flooring at zero and any asymmetry the correction introduced.
        """
        return sum(1 for sample in self.samples if sample >= metres) / len(self.samples)

    def probability_offshore_above(self, metres: float) -> float:
        """The share of the *incoming* reading's draws clearing a height.

        The question the calibrated bars are asked, on the quantity they are asked it about.
        Separate from `probability_above` rather than a flag on it, because a caller picking
        the wrong one gets a plausible number rather than an error, and this is the pair
        CONTEXT.md holds apart.
        """
        return sum(1 for sample in self.offshore_samples if sample >= metres) / len(
            self.offshore_samples
        )

    def _percentile(self, fraction: float) -> float:
        ordered = sorted(self.samples)
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[index]


@dataclass(frozen=True)
class ErrorBudget:
    """The three measured terms, wired to the files that ship them."""

    forecast: ForecastError
    translation_rmse: float
    own_error_all_hours: float
    own_error_big_swell: float
    regime_m: float

    @classmethod
    def shipped(cls, parameters: dict[str, Any] | None = None) -> ErrorBudget:
        """The budget this release carries, from the two files the analysis writes."""
        loaded = parameters if parameters is not None else load_parameters()
        residual = loaded.get("residual")
        if not isinstance(residual, dict):
            raise ValueError(
                "amplification.json carries no 'residual' block, so the Amplification "
                "Model's own error — the largest of the three uncertainty terms — cannot be "
                "read; regenerate it with analysis/amplification_model/train.py"
            )
        return cls(
            forecast=load_forecast_error(),
            translation_rmse=float(
                loaded["translations"]["significant_wave_height_m"]["residual_rmse"]
            ),
            own_error_all_hours=float(residual["all_hours"]["rmse"]),
            own_error_big_swell=float(residual["big_swell"]["rmse"]),
            regime_m=float(residual["regime_m"]),
        )

    def own_error(self, significant_wave_height_m: float) -> float:
        """The model's own residual width for a sea this size.

        Regime-split at the same 3 m bar as everything else, because the error grows with the
        sea and because conditioning here is what lets the terms be combined at all.
        """
        if significant_wave_height_m >= self.regime_m:
            return self.own_error_big_swell
        return self.own_error_all_hours

    def distribution(
        self,
        model: AmplificationModel,
        readings: dict[str, float],
        lead_time_days: int,
        *,
        gold_day_height_m: float | None = None,
        model_spread: Spread | None = None,
        draws: int = DRAWS,
        seed: int = SEED,
    ) -> PredictiveDistribution:
        """Evaluate the model many times under the measured errors, and collect the spread.

        The incoming reading is corrected and perturbed on the input side, the model is run on
        each perturbed reading, and its own residual is added to each result on the output
        side. That ordering is the whole point: it is how a metre of forecast error becomes
        1.083 metres of uncertainty about the wave a person would fly for.

        `model_spread` is the fourth term and the only one measured live rather than shipped:
        what the independent wave models said about *this* hour. `_drift_floor` records why it
        may raise the drift and never lower it. `None` — an unreachable ensemble, too few
        organisations, or a Hindcast with no ensemble to consult — leaves the distribution
        exactly as it was, which is ADR 0003's requirement that a missing provider degrade the
        uncertainty estimate rather than the prediction.
        """
        sea = float(readings[SEA])
        lead = self.forecast.at(lead_time_days)
        measured = lead is not None

        if lead is not None:
            band = lead.for_sea(sea)
            drift, bias = band.noise, band.bias
        else:
            drift, bias = self._unmeasured_drift(lead_time_days, sea)

        # Two input-side terms, different quantities, combined where they both live. The
        # ensemble raises the first rather than joining them, because it and the archive
        # measure overlapping things — see `_drift_floor`.
        input_sigma = math.hypot(self._drift_floor(drift, model_spread), self.translation_rmse)
        output_sigma = self.own_error(sea)

        # The correction #14 asks for, applied before anything is widened. `bias` is
        # (forecast - settled analysis), so a forecast reading low carries a negative bias
        # and subtracting it lifts the centre.
        centre = sea - bias

        rng = random.Random(seed)
        samples = []
        offshore = []
        for _ in range(draws):
            perturbed = dict(readings)
            incoming = max(0.0, centre + rng.gauss(0.0, input_sigma))
            perturbed[SEA] = incoming
            offshore.append(incoming)
            predicted = model.predict(perturbed).significant_wave_height
            samples.append(max(0.0, predicted + rng.gauss(0.0, output_sigma)))

        built = PredictiveDistribution(
            samples=tuple(samples),
            offshore_samples=tuple(offshore),
            lead_time_days=lead_time_days,
            measured=measured,
        )
        if gold_day_height_m is None:
            return built
        return replace(
            built, gold_day_probability=built.probability_offshore_above(gold_day_height_m)
        )

    def _drift_floor(self, drift: float, model_spread: Spread | None) -> float:
        """The archive's drift, raised to the ensemble's disagreement where that is larger.

        **Not added, and not substituted.** Adding them in quadrature would double-count:
        both are answers to "how wrong might this forecast be", and this module claims
        independence only where it is earned. Substituting would throw away whichever term
        the other cannot see — the archive measures one provider's own change of mind against
        its settled analysis, which is blind to an error that provider is consistently wrong
        about, while the ensemble measures where organisations differ, which is blind to an
        error they share. Neither bounds the other, so the larger is the honest "at least this
        uncertain".

        Both sides really do bind, which is what stops this being a rule with one term. From
        `analysis/model_spread/output/alignment.csv`, the 0.446 m provider range at one day is
        0.263 m of sigma against 0.130 m of big-swell drift, so the ensemble carries it; by
        six days the drift is 0.606 m against the ensemble's 0.385 m and the archive does.

        **It may only raise, and that direction is load-bearing.** The ensemble sigma is
        wrong in both directions and neither error survives a term that could narrow: three
        deterministic models sharing physics, assimilation and bugs are under-dispersed, so it
        understates; and their runs are not aligned, which `analysis/model_spread/` measures at
        6% of the spread at one day and up to 29% at six, so it overstates. `spread.py` ships
        the second uncorrected on exactly this reasoning — an inflated spread reads as doubt,
        and doubt makes the system quieter.
        """
        if model_spread is None:
            return drift
        if model_spread.variable != SEA:
            raise ValueError(
                f"a Model Spread on {model_spread.variable!r} cannot widen a distribution of "
                f"metres of {SEA}; the two are different quantities and the resulting range "
                "would look measured"
            )
        divisor = RANGE_TO_SIGMA.get(len(model_spread.providers))
        if divisor is None:
            return drift
        return max(drift, model_spread.value / divisor)

    def _unmeasured_drift(self, lead_time_days: int, sea: float) -> tuple[float, float]:
        """Width past the edge of the archive, and the last correction the archive measured.

        The width continues at the rate the archive measured over its last two Lead Times,
        rather than freezing at the seven-day band — eight days out is not seven days out, and
        pretending otherwise is the silent narrowing this module exists to avoid.

        The correction does the opposite: it holds. The two terms are extrapolated differently
        on purpose, and the reason is the direction each one's error points. A frozen width
        would claim uncertainty stops growing on the day the evidence runs out, which is a
        false claim of certainty. A growing correction would claim an under-read nobody
        measured, and unlike a width it moves the *centre* — the tail rate is -0.092 m a day,
        which reaches -0.87 m by day 14 and would lift a 5 m sea's centre by 19% on no
        evidence, in the one direction that manufactures Go Calls.

        Dropping the correction to zero out here is not the cautious middle, which is what the
        first version of this took it for. It puts a 0.25 m cliff at a fixed calendar
        boundary: a date crossing from eight days out to seven gained a quarter of a metre for
        methodological rather than weather reasons — an order of magnitude above the sampling
        wobble either side of it — and #15's eighth criterion asks a user to read exactly that
        kind of movement as news about the swell.

        So the last measured correction is carried forward unchanged. Of the three rules it is
        the only one with no methodological movement anywhere: continuous at the boundary and
        flat beyond it, so every centre change a user sees out there is weather. It can never
        claim more than the archive measured. And where it is wrong it under-corrects, because
        the measured under-read is still growing at the edge — which withholds a Go Call
        rather than inventing one.
        """
        last = self.forecast.measured_through_lead_days
        final = self.forecast.at(last)
        previous = self.forecast.at(last - 1)
        if final is None or previous is None:  # pragma: no cover - parse() guarantees both
            raise ValueError("the forecast error profile has no measured tail to extend")

        per_day = max(0.0, final.for_sea(sea).noise - previous.for_sea(sea).noise)
        beyond = max(0, lead_time_days - last)
        return final.for_sea(sea).noise + per_day * beyond, final.for_sea(sea).bias
