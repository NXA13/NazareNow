# Wind across the product boundary (#51)

Whether the light-wind exemption survives being fitted against one wind product and applied to
another — and, since it does not, what to translate it by.

```bash
.venv/Scripts/python.exe analysis/wind_products/gap.py
.venv/Scripts/python.exe analysis/wind_products/gap.py --probe   # where the backfill stops
.venv/Scripts/python.exe analysis/wind_products/gap.py --check   # arithmetic, offline
```

## The question

The three wave bars are fitted in Hindcast units and translated into the units a Pipeline Run
reads. The light-wind exemption was not, on a claim that appeared in six places:

> wind reaches the fit and the Pipeline Run alike from ERA5

**The first half is true.** `hindcast.wind()` reads ERA5 from the archive endpoint, and the
backtest's two paths — `operational_hours` and `reanalysis_hours` — both take that same series.
That is what made the claim look right to everyone who wrote it.

**The second half is false.** A Pipeline Run reads wind from `open_meteo.WEATHER_URL`, which is
`api.open-meteo.com/v1/forecast` — a forecast product, not the archive. So the exemption crossed
exactly the product boundary the wave bars are translated across, untranslated.

It mattered because the exemption has almost no margin. It is the lowest speed admitting the six
Gold Days in the fitting split that no hour passes on direction and speed alone; the calmest hour
of the windiest of those six is **16.3 km/h** and the fitted bar is **16.5**. And it is *fitted*
where the height bar and both arcs were merely *verified* — fitted numbers carry their units with
them.

## The trap, which is the finding worth keeping

`previous-runs-api.open-meteo.com` answers for dates long before its forecast archive opened, and
for those dates it returns **ERA5 verbatim** — the same series `hindcast.wind()` reads.

A translation fitted across such a span is the reanalysis regressed against itself. It reports
slope 1.0000, intercept 0.0000, residual 0.000, and the confident conclusion that there is no
product gap at all. That is this project's characteristic failure exactly: a response that looks
like agreement and is not.

`--probe` finds where the backfill stops by exact-match count rather than by documentation:

| month | hours | exact matches | mean abs. difference | verdict |
|---|---|---|---|---|
| 2021-01 … 2022-10 | 720–744 | **every one** | 0.000 | backfill (ERA5) |
| 2022-11 | 720 | 372 | 2.004 | boundary — part of each |
| 2022-12 | 744 | 3 | 3.281 | forecast |
| 2023-01 | 360 | 4 | 3.023 | forecast |

The boundary is **2022-11-16T09:00**, the first hour that differs at all. After it, exact matches
run at about 1.4% — the rate two independent series agree by coincidence when readings are
rounded to one decimal. The measurement starts the following whole day.

`pair_hours` refuses to fit at all if more than half the span matches exactly, so a provider that
extends its backfill breaks the run loudly instead of quietly reporting no gap.

## What was measured

10 m wind speed at the Proxy Target, ERA5 against the forecast product, **2022-11-17 to
2025-12-31 — 27,384 hours** both products describe, spanning three Big-Wave Seasons. ERA5 is the
binding side: the forecast archive runs to the present, the Hindcast cache stops at 2025.

At the **shortest Lead Time** the archive carries, deliberately. The base `wind_speed_10m` is the
archive's settled best match for a past hour; reading `_previous_dayN` would fold in the drift
#14 already measured and answer a different question. This is about two *products*, not about the
Lead Time axis.

`output/wind_product_gap.csv`:

| subset | hours | bias | MAE | RMSE | slope | intercept | residual | 16.5 translates to |
|---|---|---|---|---|---|---|---|---|
| all hours | 27,384 | −1.755 | 3.234 | 4.147 | 0.9182 | −0.4185 | 3.696 | 14.73 |
| exemption band (< 20 km/h) | 18,798 | −1.513 | 3.016 | 3.854 | 0.8320 | +0.4773 | 3.451 | **14.21** |
| straddling the bar (14.5–18.5) | 4,945 | −2.140 | 3.487 | 4.425 | 0.9852 | −1.8965 | 3.874 | 14.36 |

Bias is forecast minus Hindcast, in km/h; negative means the live feed reads **lighter**.

**The gap is not small.** ADR 0011 guessed it would be, on the reasoning that 10 m wind speed is
far less model-dependent than a partitioned swell period. It is 1.5–2.1 km/h against a bar with
0.2 km/h of margin — roughly **ten times the margin** and four times the 0.5 km/h step the bar is
rounded to.

**The choice of band is not load-bearing.** The three subsets disagree about the slope and agree
about the answer: 14.21, 14.36 and 14.73 all round up to **14.5** or 15.0, and the two
decision-relevant bands give exactly 14.5. The shipped transform is fitted on the exemption band,
by the argument `overlap/measure.py` uses for the big-swell subset — a transform applied to a
threshold belongs in the regime that threshold operates in.

## What it cost, and what it did not fix

The backtest's recall figures do **not** move, and cannot: the fit runs in ERA5 units on both
sides, so translating the shipped file changes nothing it scores. The cost is only visible on the
serving side, and this is the part of it measurable without #28's accumulated record — how often
a shipped bar reproduces, on real weather, the verdict the fit intended (ERA5 ≤ 16.5 km/h):

| shipped bar | admitted the fit would refuse | refused the fit would admit | disagree |
|---|---|---|---|
| 16.50 km/h (untranslated) | **3,005** | 826 | 14.0% |
| 14.50 km/h (translated) | 1,790 | 1,814 | 13.2% |

Untranslated, the bar erred toward admitting hours the fit never sanctioned, at nearly **four
times** the rate it erred the other way. Translated, the two errors are balanced and the total
falls slightly.

These are hours, not calls. An hour must also clear height, period and the swell arc before the
wind condition decides anything, so this is the size of the input error the condition was working
from, not a count of changed Watches or Go Calls.

**Translating fixes where the bar sits, not how noisy the reading is.** The residual is 3.45 km/h
and 13.2% of hours still disagree with the fit's intent under the corrected bar. Stacked on the
3.18 km/h RMSE `forecast_error/` measures between one day out and the settled analysis, the wind
a Go Call is issued on carries both. No amount of moving the bar addresses that; it is an argument
for #15 rather than against this change.

## What this does not settle

1. **The exemption's shape, not just its position.** ADR 0009 assumes a single speed is the right
   form. A gap this large relative to the margin is at least as much an argument that a hard
   cutoff on a noisy reading is the wrong instrument as it is an argument about which number the
   cutoff should take.
2. **Whether the transform is stable.** It is fitted on three Big-Wave Seasons of a provider that
   changes its model composition without announcement — the same assumption `overlap/` carries
   for the wave transform, and the same reason to re-measure rather than trust it indefinitely.
3. **The wind *direction* gap is unmeasured.** Only speed is measured here, because only speed is
   compared against a fitted bar. The offshore arc is verified rather than fitted and is 160°
   wide, so it is unlikely to bind — but "unlikely" is not "measured", and that is the sentence
   this whole ticket exists to stop the repository writing.
4. **The Amplification Model's wind feature stays untranslated**, on the measurement rather than
   on the old premise: at about −0.007 m per km/h the same gap moves a prediction by roughly
   0.01 m, against a measured Amplification error of 0.356 m. Recorded here because the reason is
   now a number and should be re-checked if that coefficient ever grows.

## Files

- `gap.py` — the retrieval, the backfill probe, the transform, and the offline `--check`.
- `output/wind_product_gap.csv` — the table above.
- Raw responses cache to `data/raw/wind_products/`, gitignored and re-downloadable with no
  credentials. `calibrate.py` reads this module to translate the exemption, so a recalibration
  now needs that cache the way it already needs `overlap/`'s.
