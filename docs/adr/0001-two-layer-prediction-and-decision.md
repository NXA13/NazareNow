# Split the system into an Amplification Model and a Decision Model

Swell forecasting is already solved to a standard we cannot approach — ECMWF and WaveWatch III
are physics simulations that predict Offshore Conditions days ahead, free to consume. Building
our own swell forecaster would produce a worse version of something we can simply call. What
those models *cannot* do is resolve the Nazaré Canyon, which sits far below their ~50km grid
resolution. So we consume Offshore Conditions as an input and spend our modelling effort on
Amplification, which is genuinely unserved.

Separately, knowing the wave height does not answer the user's actual question, which is
whether to spend money on flights now or wait for a better forecast. We model that as a
distinct Decision Model consuming the Amplification Model's prediction *and its uncertainty*,
rather than folding it into a threshold on predicted height.

## Consequences

The Amplification Model must emit calibrated uncertainty, not just a point estimate — the
Decision Model is useless without it. This constrains model choice later.

The two layers can be evaluated independently: the Amplification Model on predictive accuracy,
the Decision Model on the cost of false alarms versus missed swells.
