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

**Beyond the archive, the range keeps widening and says it is unmeasured.** The wave run
archive reaches seven days. Past that the width continues at the growth rate the archive
measured and the distribution is marked `measured=False`, so the interface can be visibly more
cautious rather than quietly reusing the last band it had.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Any

from nazarenow.forecast_error import ForecastError
from nazarenow.forecast_error import load as load_forecast_error
from nazarenow.models.base import AmplificationModel
from nazarenow.models.learned import load_parameters

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
    lead_time_days: int
    measured: bool
    """Whether a Forecast Error Profile actually covered this Lead Time.

    `False` past the archive's seven days. The width is still honest — it keeps growing at the
    measured rate — but nothing was measured about it, and the interface has to be able to say
    so rather than presenting an extrapolation as evidence.
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
        """The share of the distribution clearing a height — #15's Gold Day probability.

        Read off the samples rather than a fitted normal, because the samples carry the
        model's flooring at zero and any asymmetry the correction introduced.
        """
        return sum(1 for sample in self.samples if sample >= metres) / len(self.samples)

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
        draws: int = DRAWS,
        seed: int = SEED,
    ) -> PredictiveDistribution:
        """Evaluate the model many times under the measured errors, and collect the spread.

        The incoming reading is corrected and perturbed on the input side, the model is run on
        each perturbed reading, and its own residual is added to each result on the output
        side. That ordering is the whole point: it is how a metre of forecast error becomes
        1.083 metres of uncertainty about the wave a person would fly for.
        """
        sea = float(readings["significant_wave_height"])
        lead = self.forecast.at(lead_time_days)
        measured = lead is not None

        if lead is not None:
            band = lead.for_sea(sea)
            drift, bias = band.noise, band.bias
        else:
            drift, bias = self._unmeasured_drift(lead_time_days, sea)

        # Two input-side terms, different quantities, combined where they both live.
        input_sigma = math.hypot(drift, self.translation_rmse)
        output_sigma = self.own_error(sea)

        # The correction #14 asks for, applied before anything is widened. `bias` is
        # (forecast - settled analysis), so a forecast reading low carries a negative bias
        # and subtracting it lifts the centre.
        centre = sea - bias

        rng = random.Random(seed)
        samples = []
        for _ in range(draws):
            perturbed = dict(readings)
            perturbed["significant_wave_height"] = max(0.0, centre + rng.gauss(0.0, input_sigma))
            predicted = model.predict(perturbed).significant_wave_height
            samples.append(max(0.0, predicted + rng.gauss(0.0, output_sigma)))

        return PredictiveDistribution(
            samples=tuple(samples), lead_time_days=lead_time_days, measured=measured
        )

    def _unmeasured_drift(self, lead_time_days: int, sea: float) -> tuple[float, float]:
        """Width past the edge of the archive, and no correction at all.

        The width continues at the rate the archive measured over its last two Lead Times,
        rather than freezing at the seven-day band — eight days out is not seven days out, and
        pretending otherwise is the silent narrowing this module exists to avoid.

        The *bias* is deliberately not extrapolated. A width that grows too fast is cautious;
        a correction applied where nothing was measured moves the centre of a range on
        evidence that does not exist.
        """
        last = self.forecast.measured_through_lead_days
        final = self.forecast.at(last)
        previous = self.forecast.at(last - 1)
        if final is None or previous is None:  # pragma: no cover - parse() guarantees both
            raise ValueError("the forecast error profile has no measured tail to extend")

        per_day = max(0.0, final.for_sea(sea).noise - previous.for_sea(sea).noise)
        beyond = max(0, lead_time_days - last)
        return final.for_sea(sea).noise + per_day * beyond, 0.0
