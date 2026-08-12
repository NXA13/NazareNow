# Does the Predictive Distribution contain the sea that turned up?

Ticket [#80](https://github.com/NXA13/NazareNow/issues/80). Every term in the Predictive
Distribution had been measured. Their sum had not.

`backend/src/nazarenow/distribution.py` stacks three, and each was measured against something:
forecast drift by [#14](https://github.com/NXA13/NazareNow/issues/14), the Translation residual
by [#52](https://github.com/NXA13/NazareNow/issues/52) and
[#58](https://github.com/NXA13/NazareNow/issues/58), the Amplification Model's own error by
[#13](https://github.com/NXA13/NazareNow/issues/13). Nothing ever asked whether the range the
site prints holds the outcome as often as it claims to.

It does not. **It holds it more often**, and the excess grows with Lead Time.

## Running it

```bash
.venv/Scripts/python.exe analysis/distribution_coverage/settled.py     # caches the settled Swell
.venv/Scripts/python.exe analysis/distribution_coverage/coverage.py    # findings 1 and 2
.venv/Scripts/python.exe analysis/distribution_coverage/sensitivity.py # what the one caveat costs
.venv/Scripts/python.exe analysis/distribution_coverage/coverage.py --check   # offline
```

Same honest qualification as `analysis/forecast_error/README.md`: only `--check` runs from a
clean checkout. The rest needs `data/raw/forecast_runs/` (free, no credentials) and the
training dataset (Copernicus, and only for the interval table's outcomes).

## Finding 1 — the range is too wide, and the excess grows with Lead Time

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

## Finding 2 — the gate's probability is under-confident, and only some of that is by construction

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
— and hours are not days. Converting this into calls means re-running `analysis/backtest/`, which
is the follow-up, not this ticket.

## Finding 3 — what the one flattering approximation actually costs

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
it prints mean what it says?" — with both subsets, both caveats from "What this cannot settle",
and a verdict derived from the numbers rather than written into the copy, so the page stays true
if the distribution is ever narrowed. Until then the site stated a range in metres and said
nothing about having measured it, which made this the one published claim with evidence against
it and no mention of it.

The interesting part is that the repair is not obviously in the user's favour. A range that is
too wide is a system claiming less than it knows — honest in one direction, and the direction
that costs a Traveller a trip they would have taken rather than one they should not have. Both
findings say the same thing about the Watch and Go tiers: the system currently errs toward
silence.
