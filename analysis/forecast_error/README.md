# The Forecast Error Profile

Ticket [#14](https://github.com/NXA13/NazareNow/issues/14), ADR 0004. How wrong the forecast
actually is at each **Lead Time**, measured rather than assumed, so that
[#15](https://github.com/NXA13/NazareNow/issues/15) can perturb an incoming forecast by a real
distribution and the system's stated confidence means something.

**6,192 archived hours, 2025-11-16 to 2026-07-31, at Lead Times one to seven days.** Gapless.
1,593 of those hours also carry a Proxy Target.

## Running it

```bash
.venv/Scripts/python.exe analysis/forecast_error/download_runs.py          # caches the archive
.venv/Scripts/python.exe analysis/forecast_error/download_runs.py --probe  # what it carries
.venv/Scripts/python.exe analysis/forecast_error/profile.py                # the profile
.venv/Scripts/python.exe analysis/forecast_error/profile.py --check        # the arithmetic, offline
```

`download_runs.py` is separate and cached under gitignored `data/raw/forecast_runs/`, so
re-deriving the profile does not re-download nine months of ocean and cannot pick up a
different one between two runs.

**What "reproducible by a single command" honestly means here.** Only `profile.py --check` runs
from a clean checkout; it needs nothing but the repository. The rest sits on a retrieval chain:

| Step | Needs | Credentials |
|---|---|---|
| `download_runs.py` | network | none — Open-Meteo is free |
| `analysis/training_dataset/build.py` | `data/raw/{buoy,reanalysis,hindcast}/` | **Copernicus, for two of the three** |
| `profile.py` | both of the above | inherited |

So `profile.py` is one command **on a machine that already has the archives**, and on a fresh
clone it is the last of several — two of which need Copernicus credentials that only work in a
real terminal. That is the same shape `analysis/training_dataset/README.md` describes and the
same honest qualification: a single command over a documented, re-runnable retrieval chain, not
a single command from nothing.

Only the total-error tables depend on the training dataset. The drift tables and the
monotonicity check need `download_runs.py` alone, and therefore no credentials at all.

## The archive is two archives, and ADR 0004 describes only one of them

ADR 0004 says the Previous Runs archive "begins January 2024 — two winters". That is true of
**wind** and false of **waves**, and the wave side is the one that binds.

| Archive | Host | Begins | Established by |
|---|---|---|---|
| Wind | `previous-runs-api.open-meteo.com/v1/forecast` | between 2024-01-05 and 2024-03-01 | probing |
| **Waves** | `marine-api.open-meteo.com/v1/marine` | **2025-11-16 15:00** | probing |

`wave_height_previous_day1` first carries a value at 2025-11-17T15:00 and
`wave_height_previous_day7` at 2025-11-23T15:00. Six days apart, both pointing back to one run
at 2025-11-16T15:00 — the signature of an archive opened on that date, not of a patchy
backfill. Every hour from there to the present is populated at every Lead Time.

**Consequence: the wave side has one Big-Wave Season, not two.** ADR 0004 used "two winters,
and only a handful of genuine big-wave events" as its argument against training directly on
archived forecasts. The real archive is half of that, so the argument holds more strongly than
when it was written. ADR 0004 carries an amendment recording the correction.

`analysis/model_spread/README.md` already recorded that the previous-runs *host* has no marine
endpoint, which is still true. What had not been checked is that the marine host serves the
`_previous_dayN` variables itself. Those are two different questions and only the second one
unblocks #14.

## The Swell partition is not archived at all

This is the harder limit, and it is invisible from a status code.

Sampled on five dates spread across the archive — 2025-12-05, 2026-01-10, 2026-03-15,
2026-06-01, 2026-07-28 — two inside a Big-Wave Season and two outside it, so a partition that
existed only when the sea was interesting would show up rather than hide.

| Variable | Coverage | Verdict |
|---|---|---|
| `wave_height_previous_day1` | 120/120 hours | archived |
| `wave_period_previous_day1` | 120/120 hours | archived |
| `wave_direction_previous_day1` | 120/120 hours | archived |
| `swell_wave_height_previous_day1` | **0/120 hours** | **accepted, returns null** |
| `swell_wave_period_previous_day1` | **0/120 hours** | **accepted, returns null** |
| `swell_wave_direction_previous_day1` | **0/120 hours** | **accepted, returns null** |
| `wind_speed_10m_previous_day1` | 120/120 hours | archived |
| `wind_direction_10m_previous_day1` | 120/120 hours | archived |

The swell rows return **HTTP 200 with the variable present and every value null**, on every
date sampled. Code that requested them and checked the status would believe it had a swell
forecast archive and would find out otherwise only when the profile came back computed on
nothing — this project's characteristic failure, a response that looks like agreement and is
not. `download_runs.py --probe` regenerates the table.

One date would only ever have supported "missing on that date", which is a different claim
from "not archived" — the difference between a variable this provider does not carry and one
with a hole in January.

### What that costs, measured rather than shrugged at

Four of the Amplification Model's eight features are Swell-partition — `swell_height_m`,
`swell_period_s`, `swell_direction_sin`, `swell_direction_cos` — so #15 cannot inject a
measured forecast error into half the feature vector. From
`analysis/amplification_model/output/feature_reliance.csv`, where the full model's held-out
big-swell MAE is **0.3557 m**:

| Feature group | Archived? | Ablation cost |
|---|---|---|
| `combined_sea_m` alone | yes | **0.0307 m** |
| every other feature, as a group | mixed | 0.0240 m |
| the four Swell features, individually summed | **no** | ~0.0070 m |
| the three wind features, individually summed | yes | ~0.0073 m |

**The archive covers the feature that carries the model.** `combined_sea_m` has a standardised
coefficient of 1.09 against ≤ 0.09 for everything else, and it is archived. The unarchivable
features account for roughly 2% of the model's big-swell MAE.

Individual ablation costs do not sum — the group row is the reliable figure and the two
"individually summed" rows are indicative, given to show the split between what is archived
and what is not. The conclusion does not turn on the precision: even taking the whole 0.0240 m
group as unmeasurable, the archived feature still costs more to remove than all seven others
together.

## Finding 1 — drift within the product is clean, and grows smoothly

`output/drift_by_lead_time.csv`. The lead-N forecast against Open-Meteo's own archived best
match for the same hour: how much the model changes its mind as the date approaches, and
nothing else.

| Lead | Hours | Bias | RMSE | 5–95% | Bias share |
|---|---|---|---|---|---|
| 1 d | 6,152 | −0.002 m | 0.095 m | −0.16 to 0.14 m | 0.0% |
| 2 d | 6,128 | 0.002 m | 0.177 m | −0.24 to 0.33 m | 0.0% |
| 3 d | 6,104 | 0.008 m | 0.218 m | −0.30 to 0.42 m | 0.1% |
| 4 d | 6,080 | −0.012 m | 0.271 m | −0.42 to 0.46 m | 0.2% |
| 5 d | 6,056 | −0.021 m | 0.344 m | −0.52 to 0.54 m | 0.4% |
| 6 d | 6,032 | −0.032 m | 0.404 m | −0.70 to 0.60 m | 0.6% |
| 7 d | 6,008 | −0.050 m | 0.520 m | −0.90 to 0.74 m | 0.9% |

Roughly **0.07 m of extra uncertainty per day of Lead Time**, and essentially unbiased at every
Lead Time — the bias share never exceeds 0.9%, meaning a constant correction would remove under
1% of the squared error.

**This is the *forecast* component #15 should inject**, and the reason is worth stating: the
product's standing offset from the Hindcast the model was fitted on is already handled by the
Translations in `amplification.json`. A profile measured against the buoy instead would carry
that offset too, and injecting it would count the same error twice.

**Nothing to correct, only spread to add.** Because bias share is ~0, #15 can perturb around
the incoming forecast rather than around a shifted centre.

**It is a component, not the whole uncertainty, and #15 must not treat it as the whole.** Three
sources stack between an incoming forecast and a Predictive Distribution, and this table is only
the first:

| Source | Size | Where it is measured |
|---|---|---|
| forecast drift at 1 day | 0.095 m | this table |
| the Translation's residual | 0.217 m | `amplification.json`, `residual_rmse` |
| the Amplification Model's own big-swell error | 0.356 m | `feature_reliance.csv` |

At one day out the drift is the **smallest** of the three by some margin. A Predictive
Distribution built from drift alone would be roughly four times too narrow at short Lead Time,
and it would be narrow in exactly the situation a user is most likely to act on — a Go Call
issued close in. #15 has to carry all three; #14 measures one of them.

## Finding 2 — at size, long-range forecasts under-read the sea

The same measurement restricted to hours where the sea was at least 3 m — `BIG_SWELL_M`, the
same bar `analysis/amplification_model/train.py` selects on. 1,634 hours.

| Lead | Bias | RMSE | 5–95% | Bias share |
|---|---|---|---|---|
| 1 d | +0.012 m | 0.131 m | −0.18 to 0.25 m | 0.9% |
| 4 d | −0.005 m | 0.434 m | −0.63 to 0.70 m | 0.0% |
| 6 d | −0.138 m | 0.622 m | −1.12 to 0.84 m | 4.9% |
| 7 d | **−0.230 m** | 0.753 m | −1.24 to 0.97 m | 9.3% |

Two things change on the big days. The spread is 37–60% wider than the all-hours figure at
every Lead Time, and beyond five days a **negative bias appears**: a seven-day forecast of a
big swell under-reads what the same model later settles on by 0.23 m on average. That is drift
against the provider's own settled analysis, not against the sea — the under-read against the
buoy is larger, and finding 3 has it.

That direction is the unfavourable one for this system. A Watch tier issued at six or seven
days is reading forecasts that systematically under-state exactly the swells it exists to
catch, so the profile must be applied asymmetrically or the Watch bar set against the
under-read figure rather than the corrected one. **#15 should not treat the big-swell profile
as a scaled copy of the all-hours one.**

The subset is chosen on what the sea turned out to be, not on what the forecast said. Choosing
it on the forecast would silently drop every big swell the forecast missed, which is the
failure this table exists to find.

## Finding 3 — drift is not where most of the uncertainty lives

`output/total_error_by_lead_time.csv`. The same forecasts against the **Proxy Target** measured
at Monican02, over the 1,593 hours the two records share — **2025-11-26 to 2026-02-20**. That
span is bounded at the far end by #9's dataset, not by the archive, and at the near end by a
buoy gap. Everything in this section rests on those 1,593 hours, a quarter of the 6,192 the
drift tables use.

| Lead | All hours RMSE | Big swell RMSE | Big swell bias | Bias share |
|---|---|---|---|---|
| 1 d | 0.598 m | 0.809 m | **−0.393 m** | 23.6% |
| 4 d | 0.657 m | 0.876 m | −0.420 m | 23.0% |
| 7 d | 0.928 m | 1.184 m | **−0.689 m** | 33.9% |

**At one day out, total error is 0.598 m against 0.095 m of drift — six times larger.** Almost
none of the uncertainty at short Lead Time is the forecast changing its mind. It is the
standing gap between what Open-Meteo says about this point and what the buoy measures there.

And that gap is **systematic, not noise**: on big-swell hours the provider under-reads the
Proxy Target by 0.39 m at one day and 0.69 m at seven, with a fifth to a third of the squared
error removable by a constant correction.

### Which table answers #14's bias question

#14 asks whether "providers are systematically biased rather than merely noisy". The two
references answer two different readings of that, and blurring them would misattribute the
result:

- **As forecasters, they are not biased.** Drift's bias share is under 1% at every Lead Time on
  all hours. When Open-Meteo revises its view of a date it revises in both directions about
  equally, and there is nothing to correct — only spread to inject. The exception is big swells
  beyond five days, where finding 2 shows a real forecast bias emerging.
- **As a description of this mooring, they are.** The 0.39 m under-read is mostly *not* forecast
  bias. It is present at one day's Lead Time, where there is almost no forecasting left to be
  wrong about, so most of it is the standing difference between a model grid node and a buoy
  15 km offshore. Calling that provider bias would blame the forecast for a representation gap.

The honest summary: the systematic part is largely **not in the forecast**, and the part that is
in the forecast is largely **not systematic** — until size and range are both extreme, which is
finding 2.

**Neither table is the system's error, and neither must be quoted as it.** These are raw
provider readings against the buoy with nothing in between. A Pipeline Run puts two stages
between them — the Translations restate Open-Meteo in Hindcast units, and the Amplification
Model maps Hindcast conditions to the Proxy Target — and absorbing exactly this gap is what
those stages are for. What the table establishes is the *shape* of the gap, not its magnitude
after correction: it is systematic, it is size-dependent, and it grows with Lead Time.

## Finding 4 — the wind profile at long range is a provider artefact, not weather

ADR 0004's premise is that "forecast error grows with Lead Time". Every wave variable obeys it.
`wind_speed_10m` does not:

| Lead | 1 d | 2 d | 3 d | 4 d | 5 d | 6 d | 7 d |
|---|---|---|---|---|---|---|---|
| RMSE (km/h) | 3.18 | 4.19 | 4.99 | 6.50 | 9.69 | 10.66 | **9.46** |
| Bias (km/h) | −0.25 | −0.27 | −0.18 | −0.19 | **+3.66** | **+3.33** | −0.10 |

Error *falls* between six and seven days, and leads 5 and 6 carry a bias an order of magnitude
larger than their neighbours on either side. `output/reference_stability.csv` shows it is not a
sampling accident: leads 5 and 6 run +3 to +9 km/h high for seven consecutive months from
2025-11, then vanish in June.

**Suspected cause, not a documented one.** Open-Meteo's best match blends underlying models by
how far ahead each reaches, so the day-0 reference and a lead-5 forecast may not be the same
model — which would
put a step in the comparison exactly where the blend boundary sits. That is a plausible
mechanism and it is not confirmed; the provider documents no per-lead model composition and
nothing here reads its internals. What is measured is the step; the cause is an inference.

The wave series is the reason to believe it is the reference rather than the pairing: both go
through the same code, and `wave_height` shows monthly biases within ±0.16 m at every Lead Time
with no sign of a step.

It is worse on the days that matter. Restricted to big-swell hours the lead-5 bias rises to
**+6.78 km/h** with a 27.9% bias share, against −0.33 km/h at lead 1 — so the artefact is
largest exactly where a Watch tier would be reading it.

`profile.py` prints this check on every run rather than leaving it to a reader, because a
profile injected from leads 5 and 6 as measured would encode a provider artefact as though it
were weather. **The wind profile beyond four days is not injectable as it stands.** The cost is
small — wind is three of the eight features and about 0.007 m of ablation cost — but it should
be a stated exclusion, not a silent one.

## What this does not settle

1. **One Big-Wave Season.** Every figure rests on 2025-11-16 onward. The big-swell subset is
   1,634 hours of drift and 807 hours against the Proxy Target — enough to measure, not enough
   to claim the profile is stable between seasons. It should be re-derived after the 2026-27
   season and the two compared.
2. **The Swell partition is unmeasured**, and no amount of re-running fixes it. The only route
   is forward: a Pipeline Run that stores its raw responses accumulates a swell forecast
   archive this project owns. That is worth a ticket once #28's deployment is unparked, and it
   is the same accumulation `analysis/model_spread/README.md` names for run alignment.
3. **Nothing beyond seven days.** ADR 0004's ceiling holds and is now confirmed against the
   archive rather than the documentation. Watch-tier confidence past a week rests on Model
   Spread (#8) alone.
4. **The day-0 best match is a reference, not truth.** It is the model's settled analysis, not
   an observation. Finding 1 measures how much the forecast moves, which is the right quantity
   to inject and is not the same as how right it ends up. Finding 3 is the check on that, and
   the two disagree by a factor of six at short Lead Time.
5. **The wind bias at leads 5–6 has a suspected cause and no confirmed one.** Settling it needs
   either provider documentation of per-lead model composition or an independent wind archive
   to difference against.
6. **`END` is fixed at 2026-07-31** so the derivation is reproducible. Extending it re-runs
   cheaply — the cache is keyed by month and only new months are fetched.

## A note for #51 — now answered

[#51](https://github.com/NXA13/NazareNow/issues/51) asked whether the light-wind exemption,
fitted at 16.5 km/h with the windiest Gold Day it must admit at 16.3, survives being applied to
wind that crosses a product boundary untranslated. That is a question about **products**; this
is a measurement about **Lead Time**. Nothing here measures the product boundary, so nothing
here settled #51 — `analysis/wind_products/` did.

What this adds is a second, independent reason the margin is thin, and the two turn out to be
the same size. The exemption's margin is **0.2 km/h**. Open-Meteo's wind moves by **3.18 km/h
RMSE** between one day out and its own settled analysis, and #51 measured the product boundary
at **3.45 km/h** residual on top of a 1.5 km/h offset. The offset was correctable and has been
corrected — the exemption now ships translated, at 14.5 km/h. The two scatters were not, and
they stack: a wind reading a Go Call is issued on carries both.

## Files

| File | What it is |
|---|---|
| `download_runs.py` | Retrieval and caching. `--probe` regenerates the coverage table above. |
| `profile.py` | The profile, both references, and the monotonicity check. `--check` self-tests the arithmetic offline. |
| `output/drift_by_lead_time.csv` | Drift within Open-Meteo, per variable, Lead Time and subset. |
| `output/total_error_by_lead_time.csv` | Total error against the Proxy Target. |
| `output/reference_stability.csv` | Mean drift per calendar month, the evidence behind finding 4. |
