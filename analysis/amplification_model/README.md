# The learned Amplification Model

Ticket [#13](https://github.com/NXA13/NazareNow/issues/13). A least-squares fit on #9's
training dataset, scored against the **Heuristic Baseline** on Big-Wave Seasons neither model
was fitted on, and shipped as the active model in `backend/src/nazarenow/amplification.json`.

**Headline: it is worse overall and better where it matters.** Across all 28,426 held-out
hours it carries 0.207 m of mean absolute error against the baseline's 0.196 m. Above 3 m of
Combined Sea it carries 0.356 m against 0.403 m, and on held-out Gold Day hours 0.564 m
against 0.885 m. Both halves are stated because ADR 0006 requires the pair and because the
flattering half alone would misdescribe the model.

## Running it

```bash
.venv/Scripts/python.exe analysis/amplification_model/train.py

# The fit, the split, the feature encoding and the export, self-tested offline.
.venv/Scripts/python.exe analysis/amplification_model/train.py --check
```

The first command is the whole of training: it reads
`analysis/training_dataset/output/training_dataset.csv`, selects a model, refits it, scores
it, writes the three reports below and overwrites the parameter file the backend reads. It
needs no credentials and contacts nothing.

It does need that dataset present, and the cached archives behind
`analysis/overlap/measure.py`, which supplies the reanalysis-to-operational translation. On a
fresh clone, `analysis/training_dataset/README.md` documents the retrieval chain.

## What is being learned is not Amplification

This is the first thing to be clear about, and `CONTEXT.md` is why the wording matters.

**Amplification** is defined there as the transformation the canyon applies on the way to
Praia do Norte. What was fitted here is the difference between the Copernicus IBI reanalysis
and the buoy at Monican02 — two readings of the same patch of ocean, 1.12 km apart, both
15 km offshore of the beach. The live system already samples Open-Meteo at Monican02's own
coordinates, so the model is correcting a reanalysis against a mooring, not projecting a
swell onto a beach.

That transformation is not learnable from anything in this repository. It would need a
historical record of **Face Height** at the break, which does not exist — the reason ADR 0002
introduced a Proxy Target in the first place. `analysis/training_dataset/README.md`
limitation 1 sets this out, and #9 flagged it as the thing #13 must not assume away.

The class is called `LearnedAmplification` because it fills the Amplification Model slot in
the interface ADR 0001 draws. The name of the slot is not a claim about what it knows.

## How it was fitted

**Three splits on Big-Wave Season boundaries**, never on rows. 73,601 hourly rows are nowhere
near 73,601 independent observations, and a random split would leak neighbouring hours across
it (#9's README, limitation 3).

| Split | Seasons | Rows | |
|---|---|---|---|
| training | 2011/12–2017/18 | 28,759 | fits the coefficients |
| tuning | 2018/19–2019/20 | 12,665 | selects the feature set and weighting |
| held out | 2020/21–2025/26 | 28,426 | read once, at the end |

The chosen candidate is then refitted on training + tuning together — 41,424 rows — because
the tuning seasons were used to pick a *shape*, not to fit coefficients.

**The boundary is `calibrate.py`'s, and that is load-bearing rather than tidy.** The shipped
thresholds were fitted on 2011/12–2019/20, so scoring both models on 2020/21 onward is the
only way the *baseline* is held out too. A learned model evaluated held-out against a
baseline fitted on the same hours would win a rigged comparison.

**Rows without wind are dropped** — 763 of them, leaving 72,838. Open-Meteo always serves
wind, so a model with a wind feature must never meet a missing one at serving time.

**Monican01 is not used at all.** #9 left open whether the Offshore Observation earns its
place; the answer for #13 is that it cannot be served. It is a measurement, not a forecast,
and the running system has no access to it. That is a serving constraint, not a finding about
whether the column would have helped.

### The rarity of large swell is handled by weighting, and the choice was measured

47.2% of rows sit under 2 m and 1.0% at or above 6 m. Fitted uniformly, least squares chooses
its coefficients almost entirely from ordinary seas and is free to trade away accuracy
exactly where the system earns its keep.

So weighting was made a candidate rather than an assumption. `big-swell-weighted` weights each
row by its Combined Sea, floored at 1 m so a flat calm cannot drop out of the fit. It won on
the tuning split and it is what ships. Every figure below is also broken down by size band,
because a single aggregate over this distribution mostly describes small seas.

Selection ran on **MAE over tuning rows with Combined Sea at or above 3 m** — the regime the
system actually calls in. Defined on the *input* rather than on the measured target, because a
model has to be able to identify its own regime at serving time.

`output/candidates.csv` has all ten candidates. The spread is narrow and monotonic in richness:
`combined-sea-only` scores 0.395, `all-readings` 0.367, and adding the period interaction on
top scores 0.367 — no better, so the simpler of the two ships.

## What it scores, against the baseline, on identical held-out hours

The baseline's prediction is the offshore Combined Sea carried through unchanged, which is
what `HeuristicBaseline.predict` returns by construction. So this table asks one exact
question: does a fitted correction beat passing the Hindcast straight through?

| Held-out subset | Rows | Baseline MAE | Learned MAE | Gain |
|---|---|---|---|---|
| all hours | 28,426 | 0.196 | 0.207 | **−0.011** |
| Combined Sea ≥ 3 m | 4,473 | 0.403 | 0.356 | +0.047 |
| **Gold Day hours** | **120** | **0.885** | **0.564** | **+0.322** |
| measured target under 2 m | 15,665 | 0.119 | 0.165 | −0.046 |
| measured target 2–3 m | 7,511 | 0.203 | 0.215 | −0.012 |
| measured target 3–4 m | 3,383 | 0.308 | 0.278 | +0.030 |
| measured target 4–5 m | 1,127 | 0.467 | 0.321 | +0.146 |
| measured target 5–6 m | 415 | 0.701 | 0.449 | +0.252 |
| measured target 6 m and above | 325 | 1.031 | 0.621 | +0.410 |

Bands are on the *measured* target, so a model that mistakes big seas for small ones cannot
hide in the wrong row. `output/held_out_scores.csv` carries RMSE and bias beside these.

**The improvement is monotonic in size and the loss is confined to seas nothing is ever
called on.** The crossover sits at 3 m, and the shipped `minimum_significant_wave_height_m`
is 2.75 m — the same quantity, Combined Sea rather than swell height, so the two are directly
comparable. Nothing below that bar is ever called at all.

**The real finding is in the bias, not the MAE.** The baseline does not scatter around the
buoy — it sits **under** it, by −0.861 m on Gold Day hours and −1.016 m above 6 m. The
reanalysis systematically under-reads a mooring nearer the canyon head, and it under-reads it
worse the bigger the sea gets. The fit removes over half of that: −0.405 m and −0.362 m
respectively. It does not remove all of it, and the residual is still one-directional.

**On all hours the learned model has the better RMSE** — 0.282 against 0.297 — while having
the worse MAE. That is the weighting working as intended: it trades many small errors for
fewer large ones. Read the MAE row as "typically slightly less precise" and the RMSE as
"less often badly wrong".

### The Gold Day figure rests on five days

**120 hours across 5 Gold Days.** That is the number to hold this claim to. The held-out
seasons contain 13 Gold Days by `calibrate.py`'s count, but training also requires the buoy to
have been reporting and the wind to be present, and only 5 survive both.

Five days is far too few to carry the headline on its own, and it is not asked to: the
monotonic improvement across the 5,250 held-out hours above 3 m of measured target is the
evidence, and the Gold Day rows are a consistent, much smaller corroboration of it.

## Which inputs it relies on

`output/feature_reliance.csv`. Two measurements, because they can disagree and each is
misleading alone. The standardised coefficient is in metres of predicted target per standard
deviation of input. The ablation cost is what refitting *without* that column does to held-out
big-swell MAE.

| Feature | Standardised coefficient | Ablation cost |
|---|---|---|
| `combined_sea_m` | 1.089 | **+0.031** |
| `swell_period_s` | 0.057 | +0.004 |
| `wind_speed_kmh` | −0.057 | +0.003 |
| `swell_direction_cos` | 0.090 | +0.003 |
| `wind_direction_sin` | 0.050 | +0.003 |
| `wind_direction_cos` | 0.033 | +0.002 |
| `swell_direction_sin` | −0.059 | +0.001 |
| `swell_height_m` | 0.041 | −0.001 |
| *(all seven except `combined_sea_m`, as a group)* | | **+0.024** |

**One feature does most of the work and the other seven do the rest jointly.** Dropped
individually each looks worthless — they are collinear, so the others absorb the work.
Dropped as a group they cost 0.024 m of the 0.047 m total gain over the baseline. Roughly
half the improvement is a slope-and-intercept rescale of the Hindcast; the other half needs
the remaining columns.

### The domain sanity check the ticket asks for

Three claims, checked against `CONTEXT.md` rather than against intuition.

1. **The Combined Sea coefficient is 1.097, slightly above 1.** The model scales the
   reanalysis *up*. That is the direction the bias table already showed and it is what the
   geometry predicts: Monican02 sits nearer the canyon head than IBI's node, so it should read
   a little larger. A coefficient below 1 would have contradicted both.

2. **The direction terms peak at 318°.** `0.314·cos θ − 0.284·sin θ` is maximised at
   `atan2(−0.284, 0.314)` ≈ 317.9°, WNW–NW. The calibrated swell arc is 255–330°, fitted
   independently against Gold Days by #12 and #39. The model was never told about that arc and
   landed inside it. This is the strongest corroboration in the report: two entirely separate
   fits, on different targets, agreeing about which bearing the canyon favours.

3. **The wind speed coefficient is negative, and this one is not corroborated.** −0.007 m per
   km/h says the model expects the buoy to read *lower* than the reanalysis when it blows. A
   reading exists — the reanalysis already models wind sea, so this is a correction to its
   wind-sea contribution rather than a statement about waves — but nothing here tests it, its
   ablation cost is 0.003 m, and it should not be quoted as a finding.

## Inference cost

`output/inference_cost.csv`, measured through `LearnedAmplification.predict` rather than
through numpy, because that is the path `run_pipeline` actually takes.

**13.2 µs per prediction, ~76,000 per second.** ADR 0004 requires this because #15 will run
the model hundreds of times per forecast date to build a Predictive Distribution: 500
evaluations across a 14-day range is 7,000 predictions, about **0.09 s**. Comfortably viable,
with three orders of magnitude of headroom.

## How it is served, and what it is allowed to change

The active model is chosen by **`NAZARENOW_MODEL`**, read per Pipeline Run, following
`NAZARENOW_THRESHOLDS` and `NAZARENOW_DB`. It defaults to `learned-amplification`. Setting it
to `heuristic-baseline` restores the rule of thumb, which ADR 0006 keeps runnable
permanently — it is the benchmark every figure above is measured against. An unrecognised
name fails the run rather than falling back.

**The swap changes the predicted height and cannot change a call.** `LearnedAmplification`
delegates every `Condition` verdict to the real `HeuristicBaseline`, and `decide` branches on
those identities alone. This is deliberate and not merely conservative: the shipped
`minimum_significant_wave_height_m` was fitted against *offshore Open-Meteo wave height*, and
the learned model emits a predicted Proxy Target. Judging the new quantity against the old bar
would be the units conflation `CLAUDE.md` calls load-bearing. Retiering on a learned height is
a recalibration, and it belongs to a ticket that fits the bar to it.

It is also what makes shipping this on 5 held-out Gold Days defensible: the worst case of a
bad fit is a wrong number beside a correct call, not a wrong call.

### Fitted on a reanalysis, served a forecast

#9's README warned that ADR 0004 covers only one train/serve skew, and that IBI's swell period
reads systematically high against the operational feed — by enough that #39 had to refit the
thresholds rather than carry them across. A Forecast Error Profile corrects forecast noise and
cannot correct a fixed difference between two products. ADR 0011 records this as a consequence
of reading waves from one product and serving another.

This is handled the way `backtest.py` already handles it: the fit stays in its native
reanalysis units, and incoming Open-Meteo readings are restated into those units by
`Translation.invert` before the coefficients are applied. The two translations ride in the
parameter file, so the backend applies them without importing analysis code:

```
significant_wave_height_m: operational = 0.9412 x reanalysis + 0.3435
swell_period_s:            operational = 0.9307 x reanalysis + 0.2924
```

Both fitted on 4,366 overlapping hours at or above 3 m — the regime the model operates in, and
the regime `analysis/overlap/README.md` measured the relationship is *not* constant across.

**That subset is selected on Open-Meteo's *Swell* height, not on Combined Sea**, and the
distinction is not cosmetic. `measure.fit_translations` filters `operational_height`, which is
`swell_wave_height`; this README, `train.py:95-101` and `amplification.json` all describe the
same bar as Combined Sea. Read the way it is written the subset is 4,941 hours, not 4,366. #52
measured the consequence and it is recorded below.

## Is the Translation the right shape? (#52)

`translation_shape.py`. #52 asked whether extrapolating the Translation below its fitted range
is what costs the 3–4 m band its sign on the served path, and if so what shape does better
without giving up accuracy at size. **The answer to the first question is no, the answer to the
second is "nothing worth shipping", and the measurement turned up something larger than either
question asked about.** Nothing here is shipped: the Translation is shared with `calibrate.py`,
so changing it moves shipped decision thresholds, and that is a separate decision.

```bash
.venv/Scripts/python.exe analysis/amplification_model/translation_shape.py

# The fitting, the hinge, the inversion and the shipped-bar arithmetic, self-tested offline.
.venv/Scripts/python.exe analysis/amplification_model/translation_shape.py --check
```

### 1. Extrapolation cannot be the cause, because the band is barely extrapolated

A measured target of 3–4 m is not an input Combined Sea of 3 m and above. Of the 3,383 held-out
hours in that band, **31.9%** have an input below the 3 m everyone quotes — and only **9.5%**
fall below 2.71 m, which is where the fitted subset's Combined Sea coverage actually reaches at
its 1st percentile. Nine tenths of the band is served from inside the fitted cloud. Whatever
costs it its sign, it is not that the line was never fitted there.

The same table says something the ticket did not ask: **84.3% of all held-out hours** have an
input below 3 m. The band under investigation is one of the least extrapolated in the set.

### 2. The extrapolation defect is real, large, and somewhere else

This is the one measurement in the file that is not a bound. Both products really reported on
all 35,064 overlap hours, so a transform's error between them is observed rather than
reconstructed. Bias and RMSE of the shipped height Translation against what Open-Meteo actually
read, against the best alternative shape:

| Input Combined Sea | Hours | Shipped bias / RMSE | Regime-aware bias / RMSE |
|---|---|---|---|
| 0–1 m | 3,911 | **+0.271** / 0.277 | −0.007 / **0.060** |
| 1–2 m | 16,929 | **+0.220** / 0.240 | +0.001 / **0.094** |
| 2–3 m | 9,283 | +0.142 / 0.201 | +0.002 / **0.141** |
| 3–4 m | 3,409 | +0.078 / 0.212 | +0.005 / 0.196 |
| 4–5 m | 984 | −0.033 / 0.259 | −0.060 / 0.263 |
| 5–6 m | 359 | +0.042 / 0.270 | +0.063 / 0.276 |
| 6 m and above | 189 | −0.031 / **0.265** | +0.043 / 0.265 |
| all hours | 35,064 | +0.181 / 0.234 | −0.000 / **0.129** |

**The shipped Translation over-predicts the operational Combined Sea by 0.22–0.27 m below 2 m**,
which is 60% of the hours, and its RMSE there is three to four times the alternative's. In the
3–4 m band it is only mildly worse than the best shape available. So the extrapolation error the
ticket suspected is real and roughly three times larger than it guessed — and it is concentrated
in the bands the ticket was not asking about.

Two consequences follow, and the second is why this section exists.

At serving time `LearnedAmplification._restate` **inverts** this transform on every reading. An
Open-Meteo Combined Sea of 1.80 m is restated to 1.55 m before the coefficients see it, against
a true reanalysis-equivalent near 1.78 m. That is a 0.23 m understatement of the dominant
feature, on the great majority of hours the system serves.

Range restriction is the mechanism and it is ordinary: fitting a line on a narrow high slice of
a noisy pairing flattens its slope and lifts its intercept. The shipped line reads
`0.9412x + 0.3435`; fitted on every hour the same pairing reads `1.0127x + 0.0192`, which is
very nearly the identity. The two cross at 4.5 m, and below that the shipped line reads high.

### 3. Which means the published served table is partly measuring its own generator

`served_path.py` reconstructs what Open-Meteo would have read **using the shipped Translation**,
then scores a learned model that inverts the same Translation against a baseline that does not.
That is self-consistent, and it is the right construction for the question that module asks. It
also means the +0.34 m intercept above is injected into the baseline's reading as a free upward
shift — and the baseline's error is an *under*-read that grows with size, so somewhere in the
middle the two cancel.

`translation_shape.py` separates the generator from the transform under test and reads each band
six ways. Positive means the learned model is closer to the buoy:

| Held-out band | scored | published served | fair generator | best alternative | no scatter | scatter grown with size |
|---|---|---|---|---|---|---|
| all hours | −0.011 | **+0.035** | **−0.077** | −0.016 | −0.014 | −0.019 |
| Combined Sea ≥ 3 m | +0.047 | +0.014 | +0.027 | +0.027 | +0.045 | **−0.004** |
| measured target under 2 m | −0.046 | **+0.074** | **−0.126** | −0.034 | −0.035 | −0.035 |
| measured target 2–3 m | −0.012 | −0.032 | −0.054 | −0.024 | −0.022 | −0.023 |
| **measured target 3–4 m** | **+0.030** | **−0.043** | **−0.022** | **+0.003** | +0.005 | +0.003 |
| measured target 4–5 m | +0.146 | +0.042 | +0.057 | +0.088 | +0.110 | +0.058 |
| measured target 5–6 m | +0.252 | +0.167 | +0.161 | +0.192 | +0.212 | +0.142 |
| measured target 6 m and above | +0.410 | +0.396 | +0.356 | +0.357 | +0.375 | +0.259 |

Read the 3–4 m row left to right. Of the 0.073 m that separates the scored gain from the
published served one, **0.022 m is the reconstruction's own generator**, a further 0.025 m is
the shape of the transform, and the remaining 0.025 m is the Translation's residual scatter,
which no change of shape removes. The sign change is not one effect; it is three comparable
ones, and only the middle one is the thing #52 set out to fix.

**The `all hours` and `under 2 m` rows are the bigger finding.** Item 7 below reports those two
bands reversing *in the learned model's favour* once the served path is measured, and reads that
as the baseline paying for carrying an Open-Meteo number against an IBI-fitted expectation. Under
a generator that tracks the real pairing at every size, both reverse again and land **below** the
scored figure: +0.035 becomes −0.077, and +0.074 becomes −0.126. That reversal was the shipped
Translation's own extrapolation error being fed to the baseline as though it were the world.
Item 7 has been corrected accordingly.

### 4. No alternative is worth shipping, and one is worth not shipping

Five shapes were fitted on the same overlap hours and scored on every band: the shipped subset,
every hour, the subset read as Combined Sea, the 3–4 m band alone, and a regime-aware pair of
lines joined at 3 m. Full grid in `output/translation_shapes.csv`.

- **The 6 m and above constraint holds for all of them**, +0.336 to +0.357 against the shipped
  +0.356. Nothing here buys the middle by selling the top.
- **Nothing meaningfully buys the middle either.** The best 3–4 m result any shape reaches is
  +0.003, against +0.030 scored. The band is recovered to roughly zero, not to its scored value,
  because most of what it lost is scatter.
- **`refit on all hours` — the ticket's first-named candidate — is the one to avoid.** Its
  *height* line is excellent, but the shared subset drags the **period** line with it, and the
  period relationship really is regime-dependent: fitted on all hours it reads −0.232 s at 4–5 m
  and −0.140 s at 6 m and above, against the shipped line's −0.015 s and +0.084 s. It would
  degrade the swell period exactly where the Go Call bar operates.

### 5. What each would do to the shipped bars

`calibrate.py` restates the fitted bars through this same fit, so none of these is only an
Amplification Model change. From the fitted 2.75 m / 12.0 s / 13.5 s (`output/translation_shipped_bars.csv`):

| Candidate | Height | Watch bar | Go Call bar | Expressible as a Translation |
|---|---|---|---|---|
| shipped | 2.75 m | 11.5 s | 12.9 s | yes |
| all-hours | 2.75 m | **11.2 s** | **12.6 s** | yes |
| combined-sea-3m | 2.75 m | 11.4 s | 12.9 s | yes |
| band-fitted | 2.75 m | 11.4 s | 12.8 s | yes |
| regime-aware | 2.75 m | **11.2 s** | **12.6 s** | **no — two lines** |

**The two candidates that fix the height extrapolation both drop the Go Call bar by 0.3 s**, on
the strength of a period fit that section 4 shows is worse in the regime that bar operates in.
The height bar does not move under any of them. The light-wind exemption cannot move here at
all: its transform is fitted on wind against a different pairing.

`regime-aware` is also **not expressible as a `Translation`** — it is two lines and a knot, so
adopting it would change the type `fit_translations()` returns, which both the serving path and
the calibration consume. That is a contract change, not a constant change.

### The conclusion, and what it inherits

**Extrapolation below the fitted range is not what costs the 3–4 m band its sign; it is roughly
a third of it, with the reconstruction's generator and the irreducible residual scatter
accounting for the rest. No alternative shape recovers the band to its scored value, and the two
that come closest move a shipped decision threshold using a period fit measurably worse where
that threshold operates. The band is therefore documented rather than fixed.**

The finding that outlived the question is section 2: **the shipped Translation carries 0.22–0.27 m
of bias below 2 m of Combined Sea, and the Amplification Model inverts it on 84% of the hours it
serves.** That is an observation, not a bound, and it is not what #52 was opened about. It argues
for a follow-up that refits the height transform without touching the period one — which the
shared return type of `fit_translations()` does not currently allow.

**Everything except section 2 inherits `served_path.py`'s reconstruction assumption**, item 7
below: the operational series is generated from a measured transform plus noise at its measured
residual RMSE, assumed independent of sea state. The default run scores every candidate under a
residual grown with the sea as well as a flat one, and the conclusion above holds under both —
the 3–4 m column moves by 0.000 m between them. **One figure does not survive the swap**: the
aggregate `Combined Sea ≥ 3 m` gain falls from +0.027 to −0.004, because a size-weighted
residual costs the learned model most where it inverts the largest readings. The 6 m and above
band stays firmly positive (+0.259 against +0.356), so the project's central claim is unaffected,
but the ≥ 3 m aggregate should not be quoted as robust to this assumption.

## What this does not settle

1. **Five held-out Gold Days.** Stated above and repeated here because it is the limit on the
   headline claim. The band-wise evidence is much broader, but the Gold Day figure specifically
   rests on five days and should never be quoted without that.

2. **The model is worse below 3 m, and the crossover was not fitted.** 3 m is where the bands
   change sign, and it is also the constant used to define the selection regime. Those two
   things agreeing is convenient rather than established — nothing here fitted the crossover,
   and a different weighting would move it.

3. **The translation is assumed stable back to 2011.** It is fitted on 2022–2025, the only
   span where both series exist, and applied to a fit running from 2011. `analysis/overlap/`
   flags the same assumption for the same reason, and it cannot be checked with the data this
   project has.

4. **Nothing here re-scores Watch or Go Call accuracy.** By construction the swap cannot change
   a call, so #11's backtest figures still stand — but that also means this ticket produces no
   evidence that a *better height* would make better calls. It would take a recalibration
   against the learned quantity to find out, and that is not this ticket.

5. **A linear model was chosen, not compared against a non-linear one.** `.venv` carries no
   gradient-boosting library and none was added. The residual bias at size is one-directional,
   which is the shape that usually says a straight line is leaving something on the table.

6. **The 2010/11 season and the 2026 tail are still missing**, per #9's limitation 5. The fit
   inherits that gap; recovering it needs a Copernicus re-download.

7. **The model scored here is not quite the model that ships** — and the difference is large
   enough to change two bands' sign. Every score above is measured on Copernicus IBI reanalysis
   rows, in reanalysis units. In a Pipeline Run the learned model first inverts the translation
   on every Open-Meteo reading (`LearnedAmplification._restate`), at the cost of that
   translation's residual scatter (0.217 m on Hs, larger than the whole +0.047 m gain at
   ≥ 3 m), while the baseline carries its Open-Meteo reading through uncorrected.

   `served_path.py` measures both, and the asymmetry cuts both ways:

   | Held-out subset | Scored gain | Served gain | Served 5–95% |
   |---|---|---|---|
   | all hours | −0.011 | **+0.035** | +0.034 to +0.037 |
   | Combined Sea ≥ 3 m | +0.047 | +0.014 | +0.010 to +0.017 |
   | measured target under 2 m | −0.046 | **+0.074** | +0.071 to +0.076 |
   | measured target 2–3 m | −0.012 | −0.032 | −0.034 to −0.030 |
   | measured target 3–4 m | +0.030 | **−0.043** | −0.046 to −0.040 |
   | measured target 4–5 m | +0.146 | +0.042 | +0.033 to +0.050 |
   | measured target 5–6 m | +0.252 | +0.167 | +0.153 to +0.184 |
   | measured target 6 m and above | +0.410 | +0.396 | +0.373 to +0.417 |

   Positive means the learned model is closer to the buoy. Read it as three findings. The
   translation step **costs real ground in the middle**: 3–4 m flips from +0.030 to −0.043, and
   2–3 m gets worse. It **costs almost nothing at size**: 6 m and above holds +0.396, because
   there the baseline's under-reading dwarfs the scatter. And the aggregate and sub-2 m rows
   **reverse in the learned model's favour**, for a reason the scored table cannot show — the
   baseline serves an Open-Meteo number against an IBI-fitted expectation and carries the full
   offset, roughly +0.34 m at small seas, while the learned model corrects for it.

   > **Corrected by #52, and the third finding above is wrong.** That +0.34 m offset is not
   > what Open-Meteo does; it is what the shipped Translation *predicts* Open-Meteo does when
   > extrapolated 2 m below the range it was fitted on. Measured against the hours where both
   > products really reported, the offset at small seas is near zero and the shipped line
   > over-predicts by 0.22–0.27 m. The two reversing rows are that error being handed to the
   > baseline by the reconstruction that generated them. Under a generator that tracks the real
   > pairing at every size, `all hours` reads **−0.077** rather than +0.035 and `under 2 m`
   > reads **−0.126** rather than +0.074 — both worse than the scored figures rather than
   > better. The first two findings survive. See "Is the Translation the right shape? (#52)"
   > above; the served figures in the table are otherwise reproduced exactly by
   > `translation_shape.py`, which pins itself against them.

   So the honest reading is not "the fit is better than reported" or "worse", but *differently*
   better: **worse** than reported on ordinary days, and still decisively better on the big ones
   the project exists for.

   **This is a bound, not an observation.** Open-Meteo has no historical archive here, so what
   it would have read is generated from the measured translation plus noise at its measured
   residual RMSE, assuming that residual is independent of sea state. If it is correlated with
   size instead, these numbers move, and only an operational archive settles it. The assumption
   is conservative toward the learned model: independent noise is the worst case for a model
   that must invert it, while the baseline's exposure is a fixed offset no noise assumption
   changes.

   Note also that the translations were fitted on ≥ 3 m hours only (`fitted_on_hours: 4366`) and
   are applied to every hour served.

## Files

| File | What it is |
|---|---|
| `train.py` | The fit, the selection, the report and the export. `--check` self-tests the arithmetic, the splits and both feature encodings offline. |
| `output/candidates.csv` | Every feature set and weighting, scored on the tuning split. |
| `output/held_out_scores.csv` | Baseline against learned on each held-out subset, with RMSE and bias. |
| `output/feature_reliance.csv` | Standardised coefficients and ablation costs. |
| `served_path.py` | Both models scored on the path `run_pipeline` takes, not the one the fit was scored on. `--check` reproduces the published scored table from its own feature construction. |
| `output/served_path_scores.csv` | Scored against served, per subset, with a 5–95% interval. |
| `translation_shape.py` | #52. Alternative shapes of Translation, fitted and scored on every band, with the generator separated from the transform under test. `--check` self-tests the fitting and the shipped-bar arithmetic offline. |
| `output/translation_support.csv` | How much of each band's *input* sits below the range the shipped Translation was fitted on. |
| `output/translation_pairing_error.csv` | Each transform's bias and RMSE against the reading it claims to produce, on hours where both products reported. The one table here that assumes nothing. |
| `output/translation_shapes.csv` | Every candidate on every band under every reconstruction, with a 5–95% interval. |
| `output/translation_shipped_bars.csv` | What each candidate would do to the shipped height, Watch and Go Call bars. |
| `output/inference_cost.csv` | Measured cost per prediction, through the shipped path. |
| `backend/src/nazarenow/amplification.json` | The shipped parameters, with the provenance of the fit. |
