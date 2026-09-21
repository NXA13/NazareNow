# Does the Predictive Distribution contain the sea that turned up?

> **Correction (#82).** Findings 1, 2 and 3 were measured through a defect in `readings_at`
> that replaced every Lead Time's forecast with the settled analysis. **Finding 1's table is
> wrong from two days out** and its headline — the range being nearly twice too wide at seven
> days — does not survive. Finding 4 has the defect, the corrected numbers and what is actually
> left to repair. Findings 2 and 3 have since been re-derived on the fixed code and each
> section says what changed; finding 2's correction is the largest on this page.


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
.venv/Scripts/python.exe analysis/distribution_coverage/decompose.py  # what a Lead Time costs
.venv/Scripts/python.exe analysis/distribution_coverage/coverage.py --check   # offline
.venv/Scripts/python.exe analysis/distribution_coverage/gate_cost.py --check  # offline
.venv/Scripts/python.exe analysis/distribution_coverage/ablation.py --check  # offline
.venv/Scripts/python.exe analysis/distribution_coverage/decompose.py --check # offline
```

`decompose.py` is the odd one out: it makes point predictions rather than sampling a
distribution, so it runs in about a second and was what exposed the defect below. It writes
`output/lead_time_cost.csv` — per Lead Time and subset, the hours scored, the raw RMSE against
the Proxy Target before the bias correction, the corrected RMSE, and the mean signed error.
Lead 0 is the settled analysis, the floor the rest are read against. What the Lead Time adds in
quadrature over that floor, and what the shipped budget claims it is worth, are printed to the
terminal rather than written to the file. **It supports no published finding here.** It is kept
as the instrument: a flat `rmse_m` column across Lead Time is the signature the defect showed,
and the cheapest way to see it again.

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

## Finding 2 — re-derived on the fixed code — the gate is mildly under-confident in the middle of its range

> **What this section used to say, and why it is gone.** Built by the same `score()` call as
> finding 1, it was measured through the defect #144 fixed. Its central claim was that the
> reliability table is a *step*: every bin under 0.5 landing on 0.000 and every bin over 0.6 on
> 1.000, with 0.5–0.6 "the only bin that is ever strictly between 0 and 1". That is false.
> 136 of 140 bins are strictly between 0 and 1.
>
> The consequence ran further than the table. The step was the premise of the day-level cost
> argument below — "every hour in the 0.6–0.7 bin cleared the bar, at every Lead Time" — and
> that bin in fact never reaches 1.000 at any Lead Time. The re-derived gate cost is two days
> rather than one, spread over two dates and three Lead Times.

`output/gate_reliability.csv`. `decide` withholds a Go Call unless `height_bar_probability`
reaches `GO_CALL_MINIMUM_HEIGHT_PROBABILITY`, 0.70. That is a probability of an event that either happened or
did not — the sea clearing the calibrated height bar — so it can be scored the way any
probability is: group the hours by what was predicted, and count what happened.

A calibrated forecast puts the two columns on the diagonal. This one mostly is. At one day out,
over 6,152 archived hours:

| Predicted | Hours | Mean predicted | Actually cleared the bar |
|---|---|---|---|
| 0.0–0.1 | 3,793 | 0.003 | 0.001 |
| 0.1–0.2 | 185 | 0.151 | 0.108 |
| 0.2–0.3 | 70 | 0.243 | 0.157 |
| 0.3–0.4 | 111 | 0.336 | 0.342 |
| 0.4–0.5 | 29 | 0.424 | 0.414 |
| 0.5–0.6 | 93 | 0.545 | 0.667 |
| 0.6–0.7 | 62 | 0.658 | 0.887 |
| 0.7–0.8 | 44 | 0.743 | **1.000** |
| 0.8–0.9 | 89 | 0.844 | 0.989 |
| 0.9–1.0 | 1,676 | 0.991 | 0.997 |

Nine of the ten bins are strictly between 0 and 1, and the column tracks the diagonal. Across
all seven Lead Times and both term sets, **136 of 140 bins** are strictly between 0 and 1: the
four that are not are a single 44-hour bin at one day under each term set, and the empty-end
0.0–0.1 bin at four days.

What is left is a real but mild **under-confidence through the middle of the range**. Averaged
over the seven Lead Times, weighting each bin by its hours:

| Predicted | Hours | Mean predicted | Cleared | Gap |
|---|---|---|---|---|
| 0.0–0.1 | 23,118 | 0.008 | 0.003 | −0.006 |
| 0.1–0.2 | 2,492 | 0.147 | 0.100 | −0.047 |
| 0.2–0.3 | 1,375 | 0.242 | 0.205 | −0.037 |
| 0.3–0.4 | 1,063 | 0.345 | 0.357 | +0.013 |
| 0.4–0.5 | 687 | 0.439 | 0.483 | +0.044 |
| 0.5–0.6 | 895 | 0.547 | 0.598 | +0.050 |
| 0.6–0.7 | 907 | 0.652 | 0.722 | **+0.070** |
| 0.7–0.8 | 1,163 | 0.756 | 0.800 | +0.044 |
| 0.8–0.9 | 1,490 | 0.846 | 0.903 | +0.057 |
| 0.9–1.0 | 9,370 | 0.989 | 0.988 | −0.002 |

Both ends are calibrated — the two bins holding 32,488 of the 42,560 scored hours sit within
0.006 of their own predictions. The middle leans under-confident, worst at 0.6–0.7 and by seven
points, and 16 of the 21 lead × bin cells between 0.5 and 0.8 lean that way. The low-middle
leans the *other* way, by about four points at 0.1–0.3. The mean signed gap across every shipped
cell is +0.023.

That is a far smaller claim than a step, and it points at the same place finding 4 does: the
range is modestly too wide in the middle and calibrated at the extremes. A distribution wider
than the outcomes justify pulls a probability toward the middle, and this is that effect seen
from the input side — at the size finding 4 measures, not the size finding 1 appeared to show.

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
| 0.4–0.5 | 29 → 0.414 | 33 → 0.576 |
| 0.5–0.6 | 93 → 0.667 | 31 → 0.613 |
| 0.6–0.7 | 62 → 0.887 | 29 → 0.828 |
| 0.9–1.0 | 1,676 → 0.997 | 1,765 → 0.997 |

Removing the term **sharpens the predictions without straightening them**: the top bin gains 89
hours and the 0.5–0.6 bin loses two thirds of its own, but every bin that is left still lands
where it did. Across all seven Lead Times the hour-weighted absolute gap falls only from 0.0176
to 0.0142, while the mean *signed* gap moves the wrong way, from +0.023 to +0.030 — the
predictions concentrate at the ends without the middle's lean going anywhere. Whatever is making
the gate under-confident, it is not the bar's own translation uncertainty.

### What that costs the tier it gates

`GO_CALL_MINIMUM_HEIGHT_PROBABILITY` is 0.70, so the 0.6–0.7 bin is withheld. Most of it cleared
the bar — 0.887 at one day, then 0.703, 0.641, 0.730, 0.774, 0.650 and 0.761 out to seven, over
62 to 209 hours a Lead Time. Those are hours where the height condition refused a Go Call and
the sea mostly did what the bar asks.

The stale version of this section said *every* hour in the bin cleared it, at every Lead Time.
That was the defect talking, and it is the single largest correction on this page: the bin never
reaches 1.000 at any Lead Time, and at three and six days it is barely above the 0.65 it
predicts.

**This is not a count of lost Go Calls and must not be read as one.** The height condition is
one of several a Go Call rests on — swell period is the one the calibration found actually binds
— and hours are not days.

**#96 did the conversion, and it is much smaller than the hours suggest.** `gate_cost.py` runs
the full Go Call rule at every Lead Time, once with the gate and once without. Re-derived on the
fixed code, the gate takes **at most 2 of 14 Go Call days**, and only at three Lead Times:

| Lead | Go Call days, ungated | gated | withheld |
|---|---|---|---|
| 2 d | 14 | 14 | 0 |
| 3 d | 14 | 12 | **2** |
| 4 d | 15 | 14 | **1** |
| 5 d | 15 | 15 | 0 |
| 6 d | 15 | 14 | **1** |
| 7 d | 14 | 14 | 0 |

Two dates account for all of it — **2026-02-21** and **2026-03-29** — and neither is
2025-12-13, the only Gold Day in the span. The Gold Day survives the gate at every Lead Time.

This is a larger cost than the stale version claimed (it said one day, 2026-02-21, at every Lead
Time from two out to seven) and a differently shaped one: the withholding is intermittent rather
than uniform, which is what a probability sitting near a threshold looks like rather than a
systematic refusal.

**It runs over a wider archive than the tables above.** Those are joined to the Proxy Target and
so stop at 2026-02-20; `gate_cost.py` needs no outcome, only a forecast, so it spans the whole
run archive — **2025-11-16 to 2026-07-31**. That is a partial Big-Wave Season plus four months of
summer, which is why every row is reported twice, `all` and `Oct-Mar only`. Every Go Call count
and every withheld count is identical under both scopes — each Go Call day falls inside Oct-Mar
anyway — and only the denominator moves, 251–257 days against 129–135. Both withheld dates,
2026-02-21 and 2026-03-29, fall *outside* the window the tables above cover, which stops at
2026-02-20.

The shortest Lead Time shows no Go Calls to withhold, and the reason is availability rather than
the gate: `go_call_is_available` requires `CONFIRMED_THROUGH < lead_time_days`, so at one day out
the tier does not exist and those fifteen days are Confirmed instead. Separately, the gate can
never reduce a Confirmed at any Lead Time, because `decide` assigns that status in a branch that
does not read the probability.

So what is left of the bin table's alarming shape — a band leaning seven points under-confident
rather than a band in which every hour cleared the bar — costs two days out of fourteen, at the
worst Lead Time, and never the day that mattered. That is worth knowing before spending #82's
repair on it.

## Finding 3 — re-derived on the fixed code — what the one flattering approximation actually costs

> Re-derived after #144, and again after #145. This section measured what the settled-feature
> approximation costs, and the defect *was* that approximation, applied to the one feature the
> section assumed was exempt — so its premise was the thing most at risk. It survived both
> times: the centre shifts are unchanged to three decimals, because they depend on the size of
> the perturbation rather than on where the centre sits. What moves is the coverage column,
> which was finding 1's and is now finding 4's.

`output/settled_feature_cost.csv`. Seven of the model's eight features go unperturbed by
`distribution`, because the Swell partition is not archived at any Lead Time (ADR 0004's #14
amendment). This measurement therefore feeds them **settled**, which hands the distribution a
better-placed centre than a Pipeline Run has — and every result above rests on that being small.

It is. Perturbing them by the Combined Sea partition's own measured drift, over three passes:

| Lead | Median centre shift | p95 | Median, as share of half-width | Coverage, settled | Coverage, perturbed |
|---|---|---|---|---|---|
| 1 d | 0.006 m | 0.017 m | 0.9% | 94.9% | 94.8% |
| 2 d | 0.010 m | 0.031 m | 1.4% | 95.0% | 95.0% |
| 3 d | 0.013 m | 0.039 m | 1.5% | 95.9% | 95.9% |
| 4 d | 0.015 m | 0.048 m | 1.7% | 96.5% | 96.5% |
| 5 d | 0.019 m | 0.059 m | 1.8% | 95.0% | 94.8% |
| 6 d | 0.024 m | 0.076 m | 2.1% | 92.7% | 92.9% |
| 7 d | 0.030 m | 0.098 m | 2.4% | 90.3% | 90.2% |

**The whole approximation is worth at most 0.23 points of coverage**, at six days, and it does
not have a consistent sign: at three and six days perturbing the features *raises* coverage
rather than lowering it. A stand-in whose effect changes direction across Lead Time is at the
noise level of this sample, which is the strongest form the conclusion can take here.

It cannot account for what finding 4 does report. The shipped range is about a third wider than
the outcomes justify in the middle — a factor of 0.72 at four days — and a fifth of a point of
coverage is not that.

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
| 1 d | 94.0% | 94.9% | 0.82 | 0.81 |
| 4 d | 98.5% | 96.5% | 0.60 | 0.72 |
| 7 d | 99.4% | **90.3%** | 0.53 | **0.98** |

The headline — *"nearly twice the width the outcomes justify"* at seven days — was manufactured
entirely by the defect. The range is calibrated there.

### The corrected ablation

Widening factor, all hours. 1.00 is calibrated, below 1 is too wide, above 1 is too narrow:

| Lead | shipped | no drift | no translation | no own_error |
|---|---|---|---|---|
| 1 d | 0.81 | 0.85 | 0.88 | 1.75 |
| 2 d | 0.79 | 0.93 | 0.85 | 1.27 |
| 3 d | 0.75 | 0.97 | 0.79 | 1.13 |
| 4 d | 0.72 | 1.06 | 0.75 | 1.00 |
| 5 d | 0.80 | 1.34 | 0.83 | 1.01 |
| 6 d | 0.88 | 1.57 | 0.89 | 1.04 |
| 7 d | **0.98** | 2.02 | 1.00 | 1.11 |

And on big swell:

| Lead | shipped | no drift | no translation | no own_error |
|---|---|---|---|---|
| 1 d | 0.91 | 0.96 | 0.97 | 2.15 |
| 2 d | 0.90 | 1.07 | 0.95 | 1.48 |
| 3 d | 0.85 | 1.10 | 0.87 | 1.25 |
| 4 d | 0.80 | 1.21 | 0.82 | 1.08 |
| 5 d | 0.91 | 1.54 | 0.93 | 1.15 |
| 6 d | 0.87 | 1.55 | 0.87 | 1.03 |
| 7 d | **1.02** | 2.10 | 1.03 | 1.17 |

**The drift term is essential and about the right size.** Removing it now *under*-covers hard —
67.5% at seven days all hours and 64.6% on big swell, a factor above 2 — where under the defect
it appeared to calibrate the distribution. That reversal is the whole correction in one column.

**`own_error` is load-bearing at short Lead Time**, exactly as before: removing it leaves 67.5%
coverage at one day all hours and 59.5% on big swell. This is the one conclusion neither defect
touched, because at one day the forecast and the settled analysis nearly coincide.

**`translation_rmse` is inert**, also unchanged: removing it moves the factor by at most 0.069
(all hours at one day), and by under 0.02 at seven days — 0.018 all hours and 0.010 on big
swell. At 0.130 m it is swamped in quadrature. It is neither the problem nor worth touching.

### So what is left to repair

A real but modest over-width in the **middle of the range**, and one row at the far end. The
shipped factor dips to 0.72 all hours at four days and 0.80 on big swell — a range about a third
wider than the outcomes justify — then climbs back to 0.98 and 1.02 by seven. Seven days is the
one Lead Time where the range runs *narrow*, and since #145 it does so in **one** subset rather
than both: 89.6% coverage on big swell against the 90% it claims, against 90.3% all hours, which
clears its claim with a shade of width still in hand.

That split is #145's doing and it is worth being precise about. Seven hours of instrument fault,
every one of them above 8 m and every one inside this 1,593-hour window, inflated the measured
error at every Lead Time; withholding them pulled the all-hours far end back over its claim and
left the big-swell one under. The fault made the range look worse than it is, which is the
direction that costs a Traveller a trip rather than sending them on a bad one — but it also
meant the page carried a two-subset claim where only one subset ever had the finding in it.

That is a different ticket from the one #82 was written as. There is no dominant oversized term
to re-measure and no growth rate to refit; there is a mid-range bulge and a long-lead edge that
has no slack left in it. **Whether it is worth touching at all is a judgement**, and the
direction matters: a range that runs wide costs a Traveller a trip they would have taken, while
the seven-day big-swell row is the opposite error on the days the system exists to call.

**`GO_CALL_MINIMUM_HEIGHT_PROBABILITY` still moves with any change**, for the reason "What
follows" gives below — and that reason is now stronger, not weaker, because the distribution
turns out to be close to calibrated and a correction to it is a smaller, sharper change to every
`height_bar_probability` than a near-halving would have been.

### A second defect, unrelated — found here, fixed in #145

The Proxy Target carried an **instrument fault on 2026-01-24, 25 and 26**. The seven largest
hour-to-hour changes in the whole 14-year record — 4.17 m to 6.99 m — all fall on those three
days, against a median hourly change of 0.103 m and a 99th percentile of 0.791 m over 73,412
consecutive-hour pairs; the eighth largest is 2.33 m, in 2014. (#145 records 73,396 for that
count, taken on the local stamp, which loses 16 pairs to the autumn fold —
`analysis/training_dataset/README.md` has the reconciliation. Nothing else in the evidence
moves.) The buoy oscillates between 4.5 m
and 13.8 m hour to hour while the independent Hindcast decays smoothly through the same hours,
and it reports intermittently across all three days. Significant Wave Height is a sea-state
statistic over tens of minutes and cannot do that.

It was **not** in the Amplification Model's residual: those rows carry no wind in the training
dataset (`wind_present` is false), so the held-out fit already dropped them. Recomputing the
shipped residual from `amplification.json`'s own coefficients over the held-out seasons
reproduces 0.2820 and 0.4653 exactly, with none of these hours in it. It *was* in everything
this module measures, which scored all 46 hours of those three days.

`build.py` now withholds the seven hours the instrument actually got wrong — continuity names
the day, the ratio to the Hindcast names the hours, and the readings are kept beside the empty
target rather than deleted. `analysis/training_dataset/README.md` carries the rule and the
argument for it. The 39 remaining hours on those days are real and are still scored; this
module's window is **1,586 hours**, seven fewer than before.

The prediction made here before the fix was that the percentile figures would prove robust to
it, because 2.89% sits inside the tail the widening factor is read at and could only make the
range look *narrower* than it is. That was right in direction and too confident in size: every
table in findings 3 and 4 moved, the shipped factor fell by about 0.02 at most Lead Times, and
at seven days all hours it crossed back under 1.0 — which is a conclusion, not a rounding.

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
1,586 hours run from 2025-11-26 to 2026-02-20 and cluster into swells lasting a day or two, so
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
that costs a Traveller a trip they would have taken rather than one they should not have. That
is what findings 2 and 4 both report through the middle of the range: the system errs toward
silence there.

**It does not err that way everywhere, and that is the correction #82 leaves behind.** At seven
days both subsets run marginally *narrow* — 89.96% all hours and 88.8% on big swell, against the
90% claimed — so at the longest Lead Time the system claims slightly more than it knows, on the
days it exists for. That edge has no slack in it, and any narrowing aimed at the middle has to
leave it alone. Finding 1's old headline pointed the opposite way at exactly this Lead Time,
which is the clearest measure of how far the defect moved the conclusion.
