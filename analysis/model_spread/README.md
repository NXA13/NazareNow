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
is 11.5 s and the Go Call bar is 12.9 s (`analysis/calibration/`), so **1.4 s is the entire gap
between the recall tier and the precision tier**. Where the providers disagree by more than
that, which day earns a Watch and which earns a Go Call is inside the disagreement — which is
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

## What this does not settle

- **Whether staleness matters.** Finding 2 says run age cannot be read. It does not say the
  six-hour cadence difference is large enough to matter against the between-provider spread. That
  comparison is measurable from the Pipeline Run's own stored responses once enough have
  accumulated, and it is the same archive #14 needs for the Forecast Error Profile.
- **What the spread looks like on a real swell.** See the caveat above. The Big-Wave Season
  starts in October.
- **How spread should reach the Decision Model.** ADR 0003 wants the tiers driven by it. Nothing
  here proposes the rule, and on the evidence above that rule needs the seasonal measurement
  first.
- **Whether the roster should keep both NCEP resolutions.** They contribute one vote between
  them under `by_provider`, so the second buys robustness if one fails and nothing else.

## Files

| File | What it is |
|---|---|
| `probe.py` | The probe. `--check` self-tests the spread and provider-grouping arithmetic offline. |
| `output/coverage.csv` | Each model's horizon, nulls and interior gaps. |
| `output/spread_by_hour.csv` | Per hour and variable: the members reporting, and spread across models and across providers. |
