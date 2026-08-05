# Learn Amplification from Hindcast, then inject Forecast Error at serving time

The Amplification Model needs to learn how the canyon transforms Offshore Conditions, and that
relationship is best learned from clean inputs — ERA5 Hindcast paired with the Proxy Target,
roughly 76,000 quality-controlled hourly observations from 2010. But the system is served forecasts,
not hindcasts, and forecast error grows with Lead Time. Training on clean inputs and serving on
noisy ones is train/serve skew, and it produces a model whose test-set accuracy is meaningfully
better than its real accuracy, with no warning.

Rather than compromise the training data, we separate the two concerns. The Amplification Model
learns only the physical relationship. Forecast unreliability is characterised independently
from Open-Meteo's Previous Runs archive, which serves what each model actually predicted 1 to 7
days ahead of a past date, giving a Forecast Error Profile per Lead Time. At serving time we
perturb the incoming forecast by that profile, run the Amplification Model repeatedly, and emit
a Predictive Distribution rather than a point estimate.

## Considered Options

Training directly on archived forecasts removes the skew by construction, but the Previous Runs
archive begins January 2024 — two winters, and only a handful of genuine big-wave events. Too
few to learn from and far too few to validate against.

Training a separate model per Lead Time splits that same thin archive further, and Previous Runs
stops at seven days, leaving the Watch tier with no data at all.

## Consequences

The buoy record, not ERA5, bounds the training set. ERA5 reaches back to 1940 but the Proxy
Target begins in 2010, so the deeper archive is useful only for climatology and rarity context.
The bound is tighter than the date range suggests: coverage is uneven and two Big-Wave Seasons
are missing entirely (see ADR 0002).

Serving requires many model evaluations per forecast date rather than one, so the Amplification
Model must be cheap to evaluate. This effectively rules out architectures that are expensive at
inference.

Forecast Error Profiles are only measurable out to seven days. Beyond that, Watch-tier
uncertainty rests on Model Spread alone and should be presented more cautiously.

## Amendment: the Hindcast is Copernicus IBI, not ERA5 (tickets #39, #48)

Everything above about the *separation* stands unchanged. What is stale is the source it names.
The wave Hindcast is **Copernicus IBI**, ingested by #39; ERA5 now supplies only wind. **ADR
0011** records that decision and why. The three statements above that it makes wrong:

- **"ERA5 Hindcast paired with the Proxy Target"** — read Copernicus IBI. ERA5 carries no Swell
  partition at all, which is what forced the change.
- **"roughly 76,000 quality-controlled hourly observations from 2010"** — the built dataset is
  **73,601 rows from 2011-01-01**. See `analysis/training_dataset/README.md`, limitation 5.
- **"The buoy record, not ERA5, bounds the training set"** — inverted. IBI's cached download
  begins after the buoy does, so the Hindcast bounds the front. It is a download range rather
  than a limit of the product, so unlike the ERA5-era claim it is recoverable.

One thing this decision anticipated less than it appears to. It separates the physical
relationship from *forecast* error, and training on a different **product** than the one served
adds an offset no Forecast Error Profile can correct. ADR 0011 records how #13 handles it.

## Amendment: the wave run archive begins November 2025, not January 2024 (ticket #14)

The separation stands and this decision's own argument survives intact — it is strengthened.
What is wrong is a number, twice.

**"The Previous Runs archive begins January 2024 — two winters."** There are two archives, and
that describes only the wind one. Waves come from the marine host's `_previous_dayN` variables,
whose run archive begins **2025-11-16**: one Big-Wave Season, not two. Established by probing in
`analysis/forecast_error/README.md`, not read off documentation. The argument this number was
serving — that the archive is far too thin to train on and to validate against — holds more
strongly at half the depth, so the decision above is unchanged.

**The Swell partition is not archived at any Lead Time.** `swell_wave_height`,
`swell_wave_period` and `swell_wave_direction` are accepted with a `_previous_dayN` suffix and
return HTTP 200 with every value null. Four of the Amplification Model's eight features are
Swell-partition, so the Forecast Error Profile this decision promises can be measured for
Combined Sea and wind and cannot be measured for those four. The cost looks small rather than
fatal: `feature_reliance.csv` puts the archived `combined_sea_m` at a standardised coefficient
of 1.09 against ≤ 0.09 for every other feature, and removing all seven others as a group costs
less than removing it alone. #14's README carries the figures and the caveat that individual
ablation costs do not sum, so the split between archived and unarchived is indicative.

Wind is measurable only to four days. Beyond that the day-0 reference stops being one product
and the profile measures the provider's model blending rather than the weather — #14, finding 4.

One consequence is new rather than corrected. This decision assumes the profile is injected
symmetrically around the incoming forecast; #14 finds that on big-swell hours beyond five days
the forecast carries a **negative bias**, under-reading by 0.23 m at seven days *against the
provider's own settled analysis*. Against the buoy the under-read is larger again. A profile
applied symmetrically there would centre the Predictive Distribution on a number already known
to be low, so #15 inherits an asymmetry this decision did not anticipate.

A second consequence for #15. This decision reads as though the Forecast Error Profile is the
uncertainty; it is one of three components, and at one day's Lead Time the smallest — 0.095 m
of drift against a 0.130 m Translation residual and a 0.356 m Amplification error. A Predictive
Distribution built from the profile alone would be far too narrow exactly where a Go Call is
issued. (The Translation residual was 0.217 m when this was written; #58 refitted that transform
on every overlapping hour. The ordering is unchanged and the gap to the drift term has closed.)

The ceiling this decision names is confirmed against the archive rather than the
documentation: seven days, and nothing beyond it.
