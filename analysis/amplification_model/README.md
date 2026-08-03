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
cannot correct a fixed difference between two products.

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

7. **The model scored here is not quite the model that ships.** Every score above is measured on
   Copernicus IBI reanalysis rows, in reanalysis units. In a Pipeline Run the learned model first
   inverts the translation on every Open-Meteo reading (`LearnedAmplification._restate`), while
   the baseline receives its reading untouched — so the served comparison has a step in it that
   the held-out comparison does not. That step is not free: the Hs translation carries a
   `residual_rmse` of **0.217 m**, larger than the entire +0.047 m MAE gain at ≥ 3 m. It is a
   scatter around a fitted line rather than a bias, so it should not move the average much — but
   nothing here has measured that, and it cannot be measured without an operational archive to
   score against. Read the held-out table as the fit's own quality, not as a promise about what
   the site will show.

   The same inversion is applied to every hour served, though the translations were fitted on
   ≥ 3 m hours only (`fitted_on_hours: 4366`). Below 3 m the learned model is already the worse
   of the two, and that is the band most days fall in.

## Files

| File | What it is |
|---|---|
| `train.py` | The fit, the selection, the report and the export. `--check` self-tests the arithmetic, the splits and both feature encodings offline. |
| `output/candidates.csv` | Every feature set and weighting, scored on the tuning split. |
| `output/held_out_scores.csv` | Baseline against learned on each held-out subset, with RMSE and bias. |
| `output/feature_reliance.csv` | Standardised coefficients and ablation costs. |
| `output/inference_cost.csv` | Measured cost per prediction, through the shipped path. |
| `backend/src/nazarenow/amplification.json` | The shipped parameters, with the provenance of the fit. |
