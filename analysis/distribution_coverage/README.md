# Does the Predictive Distribution contain the sea that turned up?

> **Correction (#82).** Findings 1 and 2 were measured through a defect in `readings_at` that
> replaced every Lead Time's forecast with the settled analysis. **Finding 1's table is wrong
> from two days out** and its headline — the range being nearly twice too wide at seven days —
> does not survive. Finding 4 has the defect, the corrected numbers and what is actually left
> to repair. Findings 2 and 3 rest on the same call and have not yet been re-derived.


Ticket [#80](https://github.com/NXA13/NazareNow/issues/80). Every term in the Predictive
Distribution had been measured. Their sum had not.

`backend/src/nazarenow/distribution.py` stacks three, and each was measured against something:
forecast drift by [#14](https://github.com/NXA13/NazareNow/issues/14), the Translation residual
by [#52](https://github.com/NXA13/NazareNow/issues/52) and
[#58](https://github.com/NXA13/NazareNow/issues/58), the Amplification Model's own error by
[#13](https://github.com/NXA13/NazareNow/issues/13). Nothing ever asked whether the range the
site prints holds the outcome as often as it claims to.

It does not. **It holds it more often** — but only modestly, and only out to about five days.
The sentence that stood here until #82 said the excess *grows* with Lead Time, and that growth
was an artefact of the defect the correction above names.

## Running it

```bash
.venv/Scripts/python.exe analysis/distribution_coverage/settled.py     # caches the settled Swell
.venv/Scripts/python.exe analysis/distribution_coverage/coverage.py    # findings 1 and 2
.venv/Scripts/python.exe analysis/distribution_coverage/sensitivity.py # what the one caveat costs
.venv/Scripts/python.exe analysis/distribution_coverage/gate_cost.py   # finding 2, in days (#96)
.venv/Scripts/python.exe analysis/distribution_coverage/ablation.py   # finding 4 (#82)
.venv/Scripts/python.exe analysis/distribution_coverage/coverage.py --check   # offline
.venv/Scripts/python.exe analysis/distribution_coverage/gate_cost.py --check  # offline
.venv/Scripts/python.exe analysis/distribution_coverage/ablation.py --check  # offline
```

Same honest qualification as `analysis/forecast_error/README.md`: only `--check` runs from a
clean checkout. The rest needs `data/raw/forecast_runs/` (free, no credentials) and the
training dataset (Copernicus, and only for the interval table's outcomes).

## Finding 1 — SUPERSEDED BY FINDING 4 — the range is too wide, and the excess grows with Lead Time

> Every number in this section was measured through the `readings_at` defect and **the table is
> wrong from two days out**. It is preserved unedited because finding 4 quotes it, and because
> a measurement this project published and then withdrew is part of the record. Read finding 4
> first; nothing below has been corrected in place.

`output/interval_coverage.csv`. `PredictiveDistribution.range_m` is the 5th to 95th percentile
of the draws, so it claims to hold the outcome **90%** of the time. Over the 1,593 hours
carrying both an archived forecast and a Proxy Target:

| Lead | Hours | Covered | Below p5 | Above p95 | Median width | Widening factor |
|---|---|---|---|---|---|---|
| 1 d | 1,593 | 94.0% | 4.2% | 1.8% | 1.05 m | 0.82 |
| 2 d | 1,593 | 96.2% | 2.4% | 1.4% | 1.20 m | 0.73 |
| 3 d | 1,593 | 97.2% | 1.6% | 1.2% | 1.32 m | 0.66 |
| 4 d | 1,593 | 98.5% | 0.8% | 0.8% | 1.47 m | 0.60 |
| 5 d | 1,593 | 99.0% | 0.5% | 0.5% | 1.65 m | 0.55 |
| 6 d | 1,593 | 99.1% | 0.5% | 0.4% | 1.80 m | 0.55 |
| 7 d | 1,593 | 99.4% | 0.2% | 0.4% | 2.19 m | **0.53** |

The **widening factor** is the 90th percentile of the miss, in multiples of the range's own
half-width — the number the half-width would have to be multiplied by for 90% of outcomes to
fall inside. At one, the range is calibrated. At 0.53 it is nearly **twice the width the
outcomes justify**: a seven-day range spanning 2.19 m would have held 90% of what happened at
1.15 m.

**#14 predicted the sign of this and stopped one step short.** `forecast_error.json` ships the
warning that a distribution built from drift alone would be "roughly three times too narrow at
one day out", and #15 answered it by stacking the other two terms. It over-answered: the three
together are 1.2 times too wide at one day and nearly twice too wide at seven.

**Too wide, not off-centre.** The misses fall on both sides — 4.2% below against 1.8% above at
one day, 0.2% against 0.4% at seven — and the median normalised miss stays inside ±0.19 of a
half-width at every Lead Time (`median_normalised`). A displaced range misses on one side. This
one misses rarely, and roughly evenly.

**The growth is the sharper result.** A distribution that was uniformly 20% too wide would be
one number to correct. This is calibrated-ish at one day and half the required width at seven,
which says the *rate* the width grows at is wrong, not its starting point. That rate is
`_unmeasured_drift`'s per-day extrapolation and the drift table's own growth of roughly 0.07 m
per day of Lead Time — the term ADR 0004 is built on.

**Big swell is the same shape, one step behind.** Restricted to the hours the buoy measured at
3 m or more (807 of them), coverage runs 92.6% at one day to 98.9% at seven, factor 0.94 to
0.58. So the range is nearly honest at one day on the days that matter, and drifts wide the same
way. That is the subset a Go Call is issued on, and it is the more forgiving of the two.

## Finding 2 — NOT YET RE-DERIVED — the gate's probability is under-confident, and only some of that is by construction

> Built by the same `score()` call as finding 1 and so measured through the same defect. **The
> prose below is wrong and `output/gate_reliability.csv` has already been regenerated without
> it** — the file and this section no longer agree, and the file is the one to believe.
>
> The correction is large. This section's central claim is that the table is a *step*: every
> bin under 0.5 landing on 0.000 and every bin over 0.6 on 1.000, with "0.5–0.6 the only bin
> that is ever strictly between 0 and 1". Regenerated, one day out, shipped terms:
>
> | Predicted | 0.003 | 0.151 | 0.243 | 0.336 | 0.424 | 0.545 | 0.658 | 0.743 | 0.844 | 0.991 |
> |---|---|---|---|---|---|---|---|---|---|---|
> | Happened | 0.001 | 0.108 | 0.157 | 0.342 | 0.414 | 0.667 | 0.887 | 1.000 | 0.989 | 0.997 |
>
> **Nine** of the ten bins are strictly between 0 and 1, and the column tracks the diagonal. What is left
> is mild under-confidence between 0.5 and 0.7, which is a far smaller claim than the one this
> section makes. Rewriting it is its own piece of work; nothing below should be quoted meanwhile.

`output/gate_reliability.csv`. `decide` withholds a Go Call unless `height_bar_probability`
reaches `GO_CALL_MINIMUM_HEIGHT_PROBABILITY`, 0.70. That is a probability of an event that either happened or
did not — the sea clearing the calibrated height bar — so it can be scored the way any
probability is: group the hours by what was predicted, and count what happened.

A calibrated forecast puts the two columns on the diagonal. This one is a step. At one day out,
over 6,152 archived hours:

| Predicted | Hours | Mean predicted | Actually cleared the bar |
|---|---|---|---|
| 0.0–0.1 | 3,765 | 0.003 | **0.000** |
| 0.1–0.2 | 164 | 0.153 | **0.000** |
| 0.2–0.3 | 75 | 0.241 | **0.000** |
| 0.3–0.4 | 86 | 0.334 | **0.000** |
| 0.4–0.5 | 25 | 0.424 | **0.000** |
| 0.5–0.6 | 108 | 0.550 | 0.694 |
| 0.6–0.7 | 59 | 0.666 | **1.000** |
| 0.7–0.8 | 70 | 0.745 | **1.000** |
| 0.8–0.9 | 113 | 0.842 | **1.000** |
| 0.9–1.0 | 1,687 | 0.991 | **1.000** |

The system says 0.42 where the answer is always no, and 0.67 where the answer is always yes.
**Across all seven Lead Times and both term sets, 0.5–0.6 is the only bin that is ever strictly
between 0 and 1.** Everything below it never happened; everything above it always did.

That is the same fact finding 1 reports, seen from the input side: a distribution wider than the
outcomes justify pulls every probability toward the middle. Sharpness is not the complaint —
a good forecast of a nearly-determined event *should* be sharp. The complaint is that the
predictions are less sharp than the outcomes, in one direction, everywhere.

### The by-construction explanation, and why it is not the explanation

`offshore_samples` carry two terms: forecast drift, and the residual of the transform that put
the height bar into operational units. The second is uncertainty about **where the bar is**, and
since comparing a reading to a bar is symmetric, carrying it on the reading is legitimate — but
the observable outcome is a settled reading against the *shipped* bar, with no such uncertainty
in it. So some apparent under-confidence is arithmetic rather than empirical.

`coverage.py` therefore scores both, the second with the term removed. At one day, where that
term is largest relative to drift (0.130 m against 0.095 m):

| Predicted | Shipped: hours → cleared | Drift only: hours → cleared |
|---|---|---|
| 0.4–0.5 | 25 → 0.000 | 33 → 0.000 |
| 0.5–0.6 | 108 → 0.694 | 36 → **1.000** |
| 0.6–0.7 | 59 → 1.000 | 39 → 1.000 |
| 0.9–1.0 | 1,687 → 1.000 | 1,800 → 1.000 |

Removing the term **sharpens the predictions without fixing them**: the top bin gains 113 hours,
the 0.5–0.6 bin loses two thirds of its own, and what is left of it stops being graded. The step
survives. Whatever is making the gate under-confident, it is not the bar's own translation
uncertainty.

### What that costs the tier it gates

`GO_CALL_MINIMUM_HEIGHT_PROBABILITY` is 0.70, so the 0.6–0.7 bin is withheld. Every hour in it, at every Lead
Time, cleared the bar: 59 hours at one day, 163 at five, 254 at seven. Those are hours where the
height condition refused a Go Call and the sea did what the bar asks.

**This is not a count of lost Go Calls and must not be read as one.** The height condition is
one of several a Go Call rests on — swell period is the one the calibration found actually binds
— and hours are not days.

**#96 did the conversion, and it is much smaller than the hours suggest.** `gate_cost.py` runs
the full Go Call rule at every Lead Time, once with the gate and once without, and the gate
withholds **1 of 15 Go Call days**: 2026-02-21, at every Lead Time from two days out to seven. It
does not take 2025-12-13, the only Gold Day in the span.

**It runs over a wider archive than the tables above.** Those are joined to the Proxy Target and
so stop at 2026-02-20; `gate_cost.py` needs no outcome, only a forecast, so it spans the whole
run archive — **2025-11-16 to 2026-07-31**. That is a partial Big-Wave Season plus four months of
summer, which is why every row is reported twice, `all` and `Oct-Mar only`. The Go Call days are
identical under both (15 and 14); only the denominator moves, 257 days against 135. The withheld
date, 2026-02-21, falls *outside* the window the tables above cover.

The shortest Lead Time shows no Go Calls to withhold, and the reason is availability rather than
the gate: `go_call_is_available` requires `CONFIRMED_THROUGH < lead_time_days`, so at one day out
the tier does not exist and those fifteen days are Confirmed instead. Separately, the gate can
never reduce a Confirmed at any Lead Time, because `decide` assigns that status in a branch that
does not read the probability.

So the alarming shape of the bin table — a whole band in which every hour cleared the bar — costs
one day. That is worth knowing before spending #82's repair on it.

## Finding 3 — NOT YET RE-DERIVED — what the one flattering approximation actually costs

> `sensitivity.py` calls `readings_at` too, so `output/settled_feature_cost.csv` carries the
> same defect. This section measured what the settled-feature approximation costs — and the
> defect *was* that approximation, applied to the one feature the section assumed was exempt.
> It needs re-running before any of it is read.

`output/settled_feature_cost.csv`. Seven of the model's eight features go unperturbed by
`distribution`, because the Swell partition is not archived at any Lead Time (ADR 0004's #14
amendment). This measurement therefore feeds them **settled**, which hands the distribution a
better-placed centre than a Pipeline Run has — and every result above rests on that being small.

It is. Perturbing them by the Combined Sea partition's own measured drift, over three passes:

| Lead | Median centre shift | p95 | Median, as share of half-width | Coverage, settled | Coverage, perturbed |
|---|---|---|---|---|---|
| 1 d | 0.006 m | 0.017 m | 0.9% | 94.0% | 93.9% |
| 4 d | 0.015 m | 0.047 m | 1.7% | 98.5% | 98.5% |
| 7 d | 0.030 m | 0.098 m | 2.4% | 99.4% | 99.3% |

**The whole approximation is worth at most 0.12 points of coverage**, at the Lead Time where it
should bite hardest. It cannot account for a gap of nine points, and finding 1 does not depend
on it.

The stand-in errs upward: the Combined Sea is Swell plus locally-raised wind sea, and the wind
sea is the component that appears and disappears within a forecast cycle, so its drift is at
least the travelled component's. `sensitivity.py` carries the argument.

## Finding 4 — finding 1 was measuring a defect, and the budget is close to right (#82)

[#82](https://github.com/NXA13/NazareNow/issues/82) asked which of the three terms is
oversized. The answer is **none of them by much**, and getting there meant finding out why the
question looked so easy.

### The defect

`readings_at` built its feature dictionary with the lead-N Combined Sea first and `**partition`
spread **last**. `partition` comes from `settled()`, whose `SETTLED_READINGS` is
`MARINE_READINGS` — and that map carries `"significant_wave_height": "wave_height"` beside the
Swell fields. So the settled Combined Sea overwrote the forecast on every row this module ever
built.

**Every distribution in finding 1 was centred on the settled analysis at every Lead Time**,
while its width went on growing with one. Coverage then rises with Lead Time *by construction*:
the centre never degrades, and the interval around it keeps widening. That is the shape finding
1 reported as a result about the error budget.

Nothing failed, and nothing could have. The key is spelled identically in both dictionaries,
the type matches, and the value left behind is a plausible sea for the hour. Every row
validated, every join matched, every share summed to one. `settled.py`'s own header asserted
that the Combined Sea *is not fetched here*, which is false and is what made the collision
invisible to anyone reading the caller.

The only question that separates a correct row from a wrong one is whether lead 7 differs from
lead 0 at all. `coverage.py --check` now asks exactly that, on a synthetic partition built to
collide, and fails on both halves if the merge order is ever restored.

### What finding 1 actually is

The table in finding 1 above is **wrong from two days out** and is kept only so this correction
has something to point at. At one day the defect barely bites — a lead-1 forecast and the
settled analysis are nearly the same reading — which is why that row survives almost unchanged.
The divergence grows with Lead Time, exactly as the mechanism predicts.

| Lead | coverage, as published | coverage, corrected | widening, published | widening, corrected |
|---|---|---|---|---|
| 1 d | 94.0% | 94.5% | 0.82 | 0.83 |
| 4 d | 98.5% | 96.1% | 0.60 | 0.73 |
| 7 d | 99.4% | **90.0%** | 0.53 | **1.00** |

The headline — *"nearly twice the width the outcomes justify"* at seven days — was manufactured
entirely by the defect. The range is calibrated there.

### The corrected ablation

Widening factor, all hours. 1.00 is calibrated, below 1 is too wide, above 1 is too narrow:

| Lead | shipped | no drift | no translation | no own_error |
|---|---|---|---|---|
| 1 d | 0.83 | 0.86 | 0.90 | 1.79 |
| 2 d | 0.80 | 0.95 | 0.86 | 1.28 |
| 3 d | 0.76 | 0.98 | 0.83 | 1.14 |
| 4 d | 0.73 | 1.07 | 0.77 | 1.01 |
| 5 d | 0.81 | 1.37 | 0.83 | 1.02 |
| 6 d | 0.89 | 1.60 | 0.91 | 1.06 |
| 7 d | **1.00** | 2.05 | 1.02 | 1.15 |

And on big swell:

| Lead | shipped | no drift | no translation | no own_error |
|---|---|---|---|---|
| 1 d | 0.93 | 0.99 | 1.00 | 2.20 |
| 2 d | 0.94 | 1.10 | 0.99 | 1.53 |
| 3 d | 0.87 | 1.13 | 0.90 | 1.29 |
| 4 d | 0.82 | 1.24 | 0.86 | 1.11 |
| 5 d | 0.95 | 1.61 | 0.97 | 1.17 |
| 6 d | 0.88 | 1.64 | 0.89 | 1.07 |
| 7 d | **1.07** | 2.18 | 1.08 | 1.22 |

**The drift term is essential and about the right size.** Removing it now *under*-covers hard —
67.2% at seven days all hours and 64.1% on big swell, a factor above 2 — where under the defect
it appeared to calibrate the distribution. That reversal is the whole correction in one column.

**`own_error` is load-bearing at short Lead Time**, exactly as before: removing it leaves 67.2%
coverage at one day all hours and 59.0% on big swell. This is the one conclusion the defect did
not touch, because at one day the forecast and the settled analysis nearly coincide.

**`translation_rmse` is inert**, also unchanged: removing it moves the factor by at most 0.07,
and by 0.01 at seven days. At 0.130 m it is swamped in quadrature. It is neither the problem nor
worth touching.

### So what is left to repair

A real but modest over-width in the **middle of the range**, and nothing at the far end. The
shipped factor dips to 0.73 all hours at four days and 0.82 on big swell — a range about a third
wider than the outcomes justify — then climbs back to 1.00 and 1.07 by seven. Big swell at seven
days is the one place the range runs *narrow*: 88.8% coverage against the 90% it claims.

That is a different ticket from the one #82 was written as. There is no dominant oversized term
to re-measure and no growth rate to refit; there is a mid-range bulge and a long-lead edge that
has no slack left in it. **Whether it is worth touching at all is a judgement**, and the
direction matters: a range that runs wide costs a Traveller a trip they would have taken, while
the seven-day big-swell row is the opposite error on the days the system exists to call.

**`GO_CALL_MINIMUM_HEIGHT_PROBABILITY` still moves with any change**, for the reason "What
follows" gives below — and that reason is now stronger, not weaker, because the distribution
turns out to be close to calibrated and a correction to it is a smaller, sharper change to every
`height_bar_probability` than a near-halving would have been.

### A second defect, unrelated and still open

The Proxy Target carries an **instrument fault on 2026-01-24, 25 and 26**. The seven largest
hour-to-hour changes in the whole 14-year record — 4.17 m to 6.99 m — all fall on those three
days, against a median hourly change of 0.103 m and a 99th percentile of 0.791 m over 73,396
consecutive-hour pairs; the eighth largest is 2.33 m, in 2014. The buoy oscillates between 4.5 m
and 13.8 m hour to hour while the independent Hindcast decays smoothly through the same hours,
and it reports intermittently across all three days. Significant Wave Height is a sea-state
statistic over tens of minutes and cannot do that.

It is 46 hours, 2.89% of this module's evaluation window, and it is **not** in the Amplification
Model's residual: those rows carry no wind in the training dataset (`wind_present` is false), so
the held-out fit already drops them. Recomputing the shipped residual from
`amplification.json`'s own coefficients over the held-out seasons reproduces 0.2820 and 0.4653
exactly, with none of these hours in it.

The percentile figures above are robust to it — 2.89% sits inside the tail the widening factor
is read at, so it can only make the range look *narrower* than it is, which is the conservative
direction for every "too wide" reading here. It has not been filtered out, and doing so needs
its own ticket: the fault is in `analysis/training_dataset/`, upstream of everything.

## What this cannot settle

**The ensemble term is absent, and it widens.** `_drift_floor` raises the drift to the
independent wave models' disagreement wherever that is larger, and it can only raise it. No
per-Lead-Time ensemble archive exists — `analysis/model_spread/` is explicit that its one live
sample sits on a 0.4 m summer sea and must not be believed — so every distribution here was
built with `model_spread=None`. `distribution.py` records the ensemble at 0.263 m of sigma
against 0.130 m of big-swell drift at one day, the archive overtaking it by six. So the running
system's range at short Lead Time is **wider** than the one measured here, and its coverage
correspondingly higher. This moves finding 1 in the direction it already points, and it moves it
most at the Lead Time where the finding is weakest.

**Hours are not independent, and every count in this file overstates its own evidence.** The
1,593 hours run from 2025-11-26 to 2026-02-20 and cluster into swells lasting a day or two, so
the independent sample behind a column is dozens, not thousands. Treat a four-point gap as
suggestive and a nine-point one as the result; and read "59 hours, all of which cleared the bar"
as a handful of swells rather than fifty-nine chances to be wrong.

**One partial Big-Wave Season, and one Gold Day in it.** The wave archive opens 2025-11-16 and
the Proxy Target join ends 2026-02-20; the only Gold Day inside that window is **2025-12-13**.
So nothing here says anything about the distribution on the days the system exists for — the
same limitation `analysis/amplification_model/README.md` records about its own held-out Gold Day
row, and the reason the "big swell" subset is drawn at 3 m rather than at a Gold Day. Nothing
here certifies a tail, and no figure in it is a calibration certificate.

## What follows

**Not a repair in this ticket.** #80 was filed to measure, and the numbers point at a change
with a price that has to be paid deliberately: narrowing the range moves every
`height_bar_probability`, and `GO_CALL_MINIMUM_HEIGHT_PROBABILITY` was priced against the current one
(`decision.py`, and `analysis/forecast_error/height_probability.py` is the measurement). A narrower
distribution with the old floor is a different Decision Model, not a better-calibrated one.

**Said on the page, though, since #94.** The repair is one ticket; stating the finding was
another, and it needed no refit. `analysis/track_record/publish.py` now reads
`output/interval_coverage.csv` and the track record page carries the table under "Does the range
it prints mean what it says?" — with both subsets, and with "What this cannot settle" above
carried into two published caveats: the absent ensemble term as one, and the correlated hours and
single Gold Day merged into the other. Both directional sentences on the page — which way the
range misses, and whether the miss grows with Lead Time — are derived from the figures rather
than written into the copy, so the page stays true if the distribution is ever narrowed. Until
then the site stated a range in metres and said nothing about having measured it, which made this
the one published claim with evidence against it and no mention of it.

The page states the `big swell` bar from the record, and does **not** describe it as the sea a Go
Call is issued on: that bar is 2.75 m <!--now:minimum_significant_wave_height_m--> in
`thresholds.json`, and this subset is drawn at 3 m as an analysis choice, as the paragraph above
says.

The interesting part is that the repair is not obviously in the user's favour. A range that is
too wide is a system claiming less than it knows — honest in one direction, and the direction
that costs a Traveller a trip they would have taken rather than one they should not have. Both
findings say the same thing about the Watch and Go tiers: the system currently errs toward
silence.
