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
