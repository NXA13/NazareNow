# What the wave models offer, before #8 differences them

Ticket #8, ADR 0003. Model Spread is the system's only planned uncertainty estimate: several
independent wave models are asked about the same date, and their disagreement is the doubt.

`analysis/forecast_models/` established **which** models return usable swell at Praia do Norte,
from one sampled hour. This establishes what differencing them will actually involve, over the
whole forecast range — and finds three things that one hour could not show.

Reproduce with, from the repository root:

```bash
.venv/Scripts/python.exe analysis/model_spread/probe.py
.venv/Scripts/python.exe analysis/model_spread/probe.py --check   # the arithmetic, offline
```

No credentials. One request to Open-Meteo. Tables land in `output/`.

## Finding 1 — the whole ensemble arrives in one request

Open-Meteo accepts `models=meteofrance_wave,dwd_ewam,dwd_gwam,ncep_gfswave025,ncep_gfswave016`
and answers with one series per model per variable, suffixed with the model name:
`swell_wave_height_dwd_gwam`, and so on.

So Model Spread costs **one** request, not five. More importantly, every member is read from a
single response at a single instant, so none of the measured disagreement is our own sampling
drifting between calls.

That removes our half of the alignment problem and leaves theirs — see finding 2.

## Finding 2 — run age cannot be read from the provider

`analysis/forecast_models/` warned that the members publish on different cadences (NCEP
six-hourly, MeteoFrance and DWD twelve-hourly), so one member's forecast can be six hours older
than another's, and differencing them naively reports our sampling of their publication
schedules as uncertainty.

The obvious fix is to read each member's run timestamp and align on it. **Open-Meteo does not
expose one on the marine endpoint.** Four ways of asking:

| Probe | Status | Result |
|---|---|---|
| `model_run=latest` | 200 | **accepted and silently ignored** — no run field appears |
| `init=latest` | 200 | **accepted and silently ignored** |
| `run=latest` | 400 | rejected — parsed as a date, `YYYY-MM-DD` expected |
| `hourly=swell_wave_height_previous_run1` | 400 | rejected — no previous-run variables here |
| `previous-runs-api.open-meteo.com/v1/marine` | 404 | the previous-runs API has no marine endpoint |

The first two are the dangerous ones. Both return **200 with the parameter ignored**, so an
implementation that sent one and trusted the status code would believe it had pinned a run
while reading whatever the latest happened to be. That is this project's characteristic
failure — a response that looks like agreement and is not — and it is why these are recorded
as a table of negative results rather than a sentence.

**Consequence for #8.** Run alignment cannot be done by asking. It has to be either inferred by
observation — polling often enough to see each member's values change, which is what the
Pipeline Run's stored raw responses will accumulate — or shown not to matter, by measuring the
staleness component against the between-provider component. Neither is settled here, and #8
should not difference models as though it were.

## Finding 3 — the ensemble shrinks with Lead Time

The members do not share a forecast horizon.

| Model | Provider | Horizon | Interior gaps |
|---|---|---|---|
| `meteofrance_wave` | MeteoFrance | 7.0 d | 0 |
| **`dwd_ewam`** | DWD | **3.3 d** | 0 |
| `dwd_gwam` | DWD | 7.0 d | 0 |
| `ncep_gfswave025` | NCEP | 7.0 d | 0 |
| `ncep_gfswave016` | NCEP | 7.0 d | 0 |

EWAM stops at 3.3 days. It is a clean horizon, not scattered dropouts — no interior gaps — so
it can be planned around rather than having to be dropped.

But it means a naive implementation computes spread from **five** models at short range and
**four** at long range, and the number moves when a member leaves rather than when the
forecasters change their minds. That lands precisely where it does most damage: ADR 0003 makes
the **Watch** the long-range tier, and Lead Time is the quantity CONTEXT.md says the system
exists to maximise. The uncertainty estimate would be least trustworthy exactly where the
system's whole value is.

## Finding 4 — five models are three providers, and that is the fix for finding 3

EWAM and GWAM are both DWD. `ncep_gfswave025` and `ncep_gfswave016` are both NCEP, two
resolutions of one model. Counting five opinions overstates the ensemble: two resolutions of one
centre's model share its physics, its assimilation and its bugs.

So `by_provider` collapses each organisation's models to one opinion — the median of its members
— and the spread is taken **across providers**, not across model identifiers. On a worked
example where DWD's models read 1.2 and 1.4, NCEP's both read 0.8 and MeteoFrance reads 1.0, the
range across providers is **0.5** where the range across models is 0.6.

This also repairs finding 3, which is the reason to prefer it over simply dropping a member:

```
  hour               models  providers  height range  period range
  2026-08-03T00:00        5          3        0.36 m        4.15 s
  2026-08-06T00:00        5          3        0.74 m        0.22 s
  2026-08-07T00:00        4          3        0.99 m        4.05 s
  2026-08-09T00:00        4          3        0.51 m        3.82 s
```

`models` falls from 5 to 4 at EWAM's horizon. **`providers` stays at 3 throughout**, because DWD
still has GWAM. Across all 88 hours of `output/spread_by_hour.csv` where only four models
report, the provider count is 3 in every one. The ensemble's composition is then constant across
every Lead Time the system issues a call at, and the spread means the same thing at two days as
at seven.

The property this rests on is worth naming, because it is luck rather than design: the model
that stops early belongs to the **one provider that runs two**. Had MeteoFrance been the short
member, DWD's duplication would not have saved the provider count and there would be no way to
keep the ensemble constant. #8 should treat "every provider has a member reaching the full
horizon" as a condition to assert rather than assume — the roster can change under us, and the
symptom would be an uncertainty estimate that quietly means something different past day three.

## What the spread looks like, with the caveat that matters

Sampled on **2026-08-03**, over the following seven days. The probe reads the live forecast, so
re-running it will not reproduce these figures — the tables in `output/` are the snapshot they
were written from.

Swell period disagreement between providers ran **0.22 s to 4.15 s** across this forecast range,
and exceeded 1.4 s on six of the seven days sampled.

That number is worth stating precisely because of what it sits next to. The calibrated Watch bar
is 11.4 s and the Go Call bar is 12.9 s (`analysis/calibration/`), so **1.5 s is the entire gap
between the recall tier and the precision tier**. It was 1.4 s until #60 moved the Watch bar down
a tenth, and the count above is unchanged by that: six of the seven days exceed 1.5 s as well,
so the tier gap widened without buying any margin against this disagreement. Where the providers
disagree by more than the gap, which day earns a Watch and which earns a Go Call is inside the
disagreement — which is
exactly the thing ADR 0003 wants Model Spread to expose, and exactly the thing the system
currently cannot say.

**This was sampled on a flat summer sea and must be re-measured before it is believed.** Swell
heights over the range were 0.4–1.2 m. Partition period on a sea that small is poorly
constrained and the partitioning algorithms disagree most when there is barely a swell to
partition — the 4.15 s spread sits on a 0.36 m sea. Whether providers disagree this much on a
Big-Wave Season swell of 4 m is **not established here**, and the honest expectation is that
they agree considerably better. The finding is that the disagreement is measurable and
sometimes larger than the tier gap, not that it is this large when it matters.

Height and period spread are also not correlated: at 2026-08-06 the providers disagreed by
0.74 m on height while agreeing to 0.22 s on period. One spread number covering both variables
would hide that.

Swell **direction** is in `output/spread_by_hour.csv` too and is the widest of the three:
60.5° between providers at the first hour, against a swell arc 75° wide. Read with the same
caveat and then some — direction is the least meaningful of the three on a 0.4 m sea, since
there is barely a swell whose bearing to disagree about. It is collected because the arc is one
of the Heuristic Baseline's conditions, not because this figure means anything yet.

## Finding 4 — staleness is real, grows with Lead Time, and errs toward caution

Added by #8. Finding 2 established that run age cannot be *read* from the provider, and left
open whether the cadence mismatch is large enough to matter. It is measurable after all, and
not from accumulated Pipeline Runs: the marine archive carries `_previous_dayN` **per model**,
so a model's own change of mind about a fixed hour can be measured directly.

Two quantities over 6,192 archived hours, 2025-11-16 to 2026-07-31 — `alignment.py`:

| Lead | Self-movement / 24 h | Provider spread | Staleness at 6 h | at 12 h | Share at 6 h | at 12 h |
|---|---|---|---|---|---|---|
| 1 d | 0.089 m | 0.446 m | 0.028 m | 0.050 m | **6.3%** | 11.2% |
| 3 d | 0.142 m | 0.482 m | 0.045 m | 0.080 m | 9.3% | 16.5% |
| 6 d | 0.333 m | 0.652 m | 0.105 m | 0.187 m | 16.1% | **28.7%** |

The archive's finest interval is 24 hours and the gap that matters is 6 to 12, so the shorter
figures are extrapolated — by a **fitted** exponent, not an assumed one. Self-movement grows as
`gap^0.83`, measured across intervals from 24 to 144 hours. A random walk would have given 0.50
and a steadily improving forecast 1.00, so neither of the two obvious assumptions would have
been right, which is the reason to fit.

**The answer to ADR 0003.** Staleness is not negligible — it is about 6% of the spread at one
day on the expected gap and reaches 29% at six days in the worst case. ADR 0003 was right to
demand this be settled before differencing.

**It is not disqualifying, for a reason that matters more than the size.** Sampling two
providers at different run ages can only make them look *more* different than they are; it
cannot make genuine disagreement disappear. So the contamination inflates Model Spread, a wide
spread reads as doubt, and doubt makes the system quieter. **The error is always toward
caution and never toward a Go Call that should not have been issued.** That asymmetry is what
makes it safe to ship the spread uncorrected while the size is documented.

What this does *not* license is quoting Model Spread as a calibrated uncertainty. It is an
upper bound on disagreement, and at long Lead Time a loose one.

**One partition mismatch, stated rather than hidden.** The archive carries `_previous_dayN`
only for Combined Sea — `analysis/forecast_error/README.md` records that every Swell variable
comes back null at every Lead Time — while Model Spread is defined on the Swell the Heuristic
Baseline decides on. Self-movement is therefore measured on Combined Sea and carried across by
argument. `alignment.py` reports both partitions' live spread side by side so the size of that
leap is visible: at the sampled instant, Combined Sea 0.15 m against Swell 0.44 m. The leap is
real and it is the main reason finding 4 is a bound rather than a correction.

## Finding 5 — what the agreement gate costs: 4 of 25 Go Call days, and neither Gold Day

Added by #8's second half, which is the part that lets Model Spread change a call. A Go Call
now requires the **lowest organisation's swell period to still clear the Go Call bar** — the
models must agree about the decision, not merely be close to each other. `agreement.py`.

The obvious place to measure that is `analysis/backtest/`, and it cannot: a Hindcast is what
the ocean did, so it holds no forecast and nothing to disagree. Run either side of the change
the backtest produces identical tables, which is right and is not a measurement.

What *can* be measured is the archive, which carries a **real Swell partition per model**. All
three organisations report it from **2024-07** — NCEP is the constraint, null through 2024-01
and partial to 2024-06 — so the gate can be scored over **18,264 hours** to 2026-07, using the
same thresholds, the same `spread.derive` and the same `agreement_at` the Pipeline Run uses:

| Rows | Days scored | Go Call days | With the gate | Withheld |
|---|---|---|---|---|
| 2023/24 *(from July)* | 92 | 0 | 0 | 0 |
| 2024/25 | 365 | 8 | 8 | 0 |
| 2025/26 *(to July)* | 304 | 17 | 13 | 4 (23.5%) |
| All | 761 | 25 | 21 | 4 (16.0%) |
| **Big-Wave Season only** | **364** | **23** | **19** | **4 (17.4%)** |

**Read the last row.** The first four are `season_of` blocks, which run October to the
following October and therefore carry summer days CONTEXT.md says cannot produce an XXL Day —
the same overcount ADR 0010 records in the Watch budget. The restricted row is exactly two
complete Big-Wave Seasons, 364 days of the 761, and it holds 23 of the 25 Go Call days and all
four of the refusals. **4 of 23 is the figure to quote.**

**Both Gold Days inside the span keep their Go Call** — 2025-02-18 and 2025-12-13, each a Go
Call before the gate and after it. Two is not a recall figure and is not offered as one; it is
a check that the gate does not bite hardest on the days the system exists for.

**Four days, and closer to two swells.** The refusals are 2026-02-25, then 2026-03-28, 03-29
and 03-31 — one day and one run of three. ADR 0010 makes the same point about the Watch budget:
days are not episodes, and a rule refusing four days is not refusing four separate times. On
this record the gate is not a steady tax; it is something that happens to a particular kind of
swell, and every instance of it so far falls in one season.

**This is a lower bound, and the direction is known.** The archive's per-model value for a past
hour is that model's settled reading of it, near enough an analysis. A real Go Call is issued
two to seven days out, and finding 4 above measures provider spread *growing* with Lead Time —
0.446 m at one day against 0.652 m at six. The models divide more when a call is actually
issued than they do here, so production withholds more than 16%.

**It also confirms finding 4's central property over two years rather than one forecast.** The
member count moves — five models on 5,627 hours, four on 10,404, three on 2,233 — and the
**organisation count is three on all 18,264 of them**. That is what finding 4 predicted from a
single sampled forecast and what the whole roster argument rests on: the model that drops out
belongs to the one organisation that runs two, so the ensemble means the same thing throughout.
Measured here on the Swell partition, which is the one Model Spread is defined on.

One limit on the surrounding figures rather than on the gate: the wind deciding which hours
would have earned a Go Call at all is ERA5's, 9.6 km inshore — the same series and the same
caveat `analysis/backtest/README.md` records. It never touches the gate, which reads period.

## What this does not settle

- **Whether the Swell partition behaves like Combined Sea under staleness.** Finding 4 measures
  self-movement on Combined Sea, because the archive carries `_previous_dayN` for that
  partition only. Only an accumulated record of the Pipeline Run's own responses settles the
  Swell case directly, and that needs #28.
- **What the gate costs at the Lead Time a Go Call is issued at.** Finding 5 measures it at
  roughly zero, because that is what the archive can express per model on the Swell partition,
  and bounds the direction of the error rather than its size.
- **What the spread looks like on a real swell.** See the caveat above. The Big-Wave Season
  starts in October. Finding 5 is measured on two real seasons and is the first figure here
  that is not from a flat summer sea.
- **Whether the roster should keep both NCEP resolutions.** They contribute one vote between
  them under `by_provider`, so the second buys robustness if one fails and nothing else.

## Files

| File | What it is |
|---|---|
| `probe.py` | The probe. `--check` self-tests the spread and provider-grouping arithmetic offline. |
| `alignment.py` | Finding 4: staleness against disagreement, per Lead Time. `--check` self-tests the ratio, the downward scaling and the fit offline. |
| `agreement.py` | Finding 5: what the Decision Model's agreement gate withholds, over two Big-Wave Seasons of archived per-model Swell. `--check` self-tests the gate and the day reduction offline. |
| `output/alignment.csv` | Self-movement, provider spread and the staleness share at both cadence gaps. |
| `output/agreement.csv` | Go Call days with and without the gate, per Big-Wave Season. |
| `output/coverage.csv` | Each model's horizon, nulls and interior gaps. |
| `output/spread_by_hour.csv` | Per hour and variable: the members reporting, and spread across models and across providers. |
