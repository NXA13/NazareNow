# The training dataset

Ticket [#9](https://github.com/NXA13/NazareNow/issues/9). The rows the Amplification Model
will be fitted on: the **Proxy Target** — Significant Wave Height measured at Monican02 —
paired hour by hour with the **Hindcast Offshore Conditions** that produced it, per ADR 0004.

The Hindcast here is **Copernicus IBI**, following #39, not the ERA5 that ADR 0004's original
text names — ERA5 supplies only wind. **ADR 0011** records that decision, and ADR 0004 carries
an amendment pointing at it ([#48](https://github.com/NXA13/NazareNow/issues/48)).

**73,601 rows, 2011-01-01 to 2026-02-20, spanning 15 season-years — 14 of which carry rows
inside a Big-Wave Season.** Every number below comes out of `build.py`, and the file it
describes is rebuilt byte-identically by one command from the cached archives.

## Running it

```bash
.venv/Scripts/python.exe analysis/training_dataset/build.py

# The join, gap and determinism rules, self-tested offline. No credentials, no download.
.venv/Scripts/python.exe analysis/training_dataset/build.py --check
```

**Nothing here fetches anything.** The three raw archives are retrieved by the tickets that
established them, each caching into `data/raw/` and each re-runnable:

| Source | Retrieved by | Cache |
|---|---|---|
| Monican01 and Monican02 | `analysis/buoy_coverage/download_observations.py` (#2) | `data/raw/buoy/` |
| Copernicus IBI Hindcast | `analysis/backtest/reanalysis.py` (#39) | `data/raw/reanalysis/` |
| ERA5 wind | `analysis/backtest/hindcast.py` (#11) | `data/raw/hindcast/` |

So **one command rebuilds the dataset from the cached archives, not from the raw sources.** On
a machine that already has `data/raw/`, `build.py` is the whole rebuild. On a fresh clone it is
the fourth command, after the three above — and two of those need Copernicus credentials, which
is why they are separate scripts owned by the tickets that established them rather than steps
inlined here. #9 asks for "a single documented command"; what is delivered is a single command
over a documented, re-runnable retrieval chain. The distinction matters to anyone trying to
reproduce this from nothing, so it is stated rather than glossed.

Keeping retrieval out is what makes the build deterministic: it cannot pick up a different
ocean between two runs. The archives are gitignored — they are large and reproducible — and so
is the dataset itself, at about 10 MB. What is committed is `output/coverage_by_season.csv`
and the digest below, which is enough to verify a rebuild without carrying the file in every
clone forever.

```
sha256  8ad77669831b2ea050d41715fa5a38fa60f1404576c2265954604c6b16b23917
```

## What a row is

One hour, keyed by UTC and carrying its Nazaré local stamp, local day and Big-Wave Season
(ADR 0008).

| Column | |
|---|---|
| `swell_height_m` | The two Hindcast swell trains as one height — root sum of squares, since partition **energies** add and heights do not |
| `swell_period_s`, `swell_direction_deg` | The primary train. There is no way to combine two periods, so the secondary's ride alongside rather than merging in |
| `secondary_swell_*` | The second train, carried whole |
| `hindcast_combined_sea_height_m` | IBI's own Combined Sea at the node — see the first limitation below before fitting on it |
| `wind_speed_kmh`, `wind_direction_deg` | ERA5 wind, with `wind_present` |
| `offshore_observed_*` | Monican01, the **Offshore Observation** — measured, 55 km out, an input and never a target — with `offshore_observation_present` |
| `proxy_target_height_m` | The target |

**Only Hs comes from Monican02.** Its peak period and direction are real measurements, and
they are measurements *of the target*, taken at the instant the model is asked to predict.
They are left out rather than carried with a warning, because a column present in a training
file is a column something eventually gets fitted on.

### The join key is the UTC hour

Not the local stamp. When Lisbon leaves summer time, 00:00 and 01:00 UTC both render as 01:00
local, so a table keyed on the local string silently keeps one of them — one hour a year,
every year, in late October, which is inside the Big-Wave Season. `reanalysis.py` made the
same choice for the same reason.

ERA5 wind is the exception, because Open-Meteo is asked for local stamps and its response
carries no UTC. On the one ambiguous stamp each autumn the wind is left **absent** rather than
given to both UTC hours or arbitrarily to one. Of the 763 rows without wind, 747 are the tail
end of 2025 where ERA5 stops before the buoy does; the remaining 16 are those autumn fold
hours, one per year the dataset covers.

**The local day is what `season` and `in_big_wave_season` are computed from**, not the UTC
instant. Portugal runs an hour ahead through late October and late March, which is exactly
where the season boundaries fall: `2016-09-30T23:00Z` is local `2016-10-01T00:00` and opens the
2016 season, though its UTC month says September. Deriving the season from UTC would have put
those boundary hours in the wrong season while `day` — computed locally — said otherwise,
disagreeing with itself inside a single row.

## Gaps are excluded and counted, never filled

An hour enters the dataset only when the Proxy Target and the whole Hindcast are genuinely
present. No interpolation, no carrying a neighbour forward, no filling a hole with a seasonal
mean. #2 found five effectively dead Big-Wave Seasons and outages running to 488 days;
interpolating across those would manufacture a training signal out of nothing, and the model
would learn it.

Quality control is `analyse_coverage`'s, imported rather than reimplemented: Copernicus flags
1 and 2 only, read at the surface DEPTH level rather than index 0 — which is the trap that
silently returns an entirely empty column.

Wind and the Offshore Observation are treated differently on purpose. They are carried where
they exist and left **visibly empty** where they do not, each with a presence flag, so a row is
never discarded because a secondary input was out. Monican01's outages are largely uncorrelated
with Monican02's, and requiring it would have cost 42% of the record for an input the learned
model may not even want.

**76,566 hours of Proxy Target exist; 73,601 of them paired.** The 2,965 that did not (3.9%)
are almost entirely a range mismatch rather than a data problem: the buoy record starts
2010-06-12 and IBI starts 2011-01-01, and at the far end the buoy runs to 2026-06-30 while IBI
stops 2026-04-21. `output/coverage_by_season.csv` reports it per season, with the available
hours from each source beside the paired count — so a season where the two sources never
overlap reads differently from one where neither had anything.

## What the record actually holds

Two of the seventeen seasons contribute nothing at all, and a third contributes nothing
**inside** the Big-Wave Season:

- **2013/14** — both moorings were down. #2 found it the only season both lost.
- **2016/17** — Monican02 recorded nothing between October and March. Its 2,137 rows are all
  from the following summer, which is why `in_big_wave_season` is the column to read and not
  `paired`.

So **14 seasons carry Big-Wave Season rows**, and 53.5% of the dataset falls inside one.

### The Proxy Target's distribution

| Proxy Target | Rows | |
|---|---|---|
| ≥ 2 m | 34,765 | 47.2% |
| ≥ 3 m | 14,845 | 20.2% |
| ≥ 4 m | 5,696 | 7.7% |
| ≥ 5 m | 2,020 | 2.7% |
| ≥ 6 m | 740 | 1.0% |
| ≥ 7 m | 283 | 0.4% |
| ≥ 8 m | 85 | 0.1% |

Reported as bands rather than as a count above one bar, deliberately. The obvious bar to reach
for is the Heuristic Baseline's `minimum_significant_wave_height_m`, and it is the wrong
quantity: that threshold is applied to *offshore swell height in a forecast*, and the Proxy
Target is the *Combined Sea* measured at a mooring. CONTEXT.md holds those apart and CLAUDE.md
calls the conflation load-bearing.

### The positive class is 21 days

**502 rows fall on a Gold Day, and they cover 21 of the 38.** Seventeen Gold Days have no rows
at all — the instrument was down, or the day predates IBI. That is the number #13 has to plan
around, and it is smaller than the 38 the calibration fits against, because the calibration
scores days from the Hindcast alone while training needs the buoy to have been reporting too.

Of the 21, nineteen are covered for all 24 hours and two — 2018-11-09 and 2018-11-18 —
contribute 23. A Gold Day is either wholly present or wholly absent here, almost without
exception: the outages are long, so they take whole days rather than nibbling at them.

## What this does not settle

**1. The Hindcast node and the Proxy Target are the same point, so what a model fits here is
not Amplification.** IBI's nearest wet node sits 1.12 km from Monican02, and the live system
already samples Open-Meteo at Monican02's coordinates. A model taking
`hindcast_combined_sea_height_m` and predicting `proxy_target_height_m` is therefore learning
the reanalysis's *local error at one mooring*, not the transformation the canyon applies on the
way to the beach. That transformation is not learnable from anything in this repository — Face
Height has no historical archive, which is the whole reason ADR 0002 introduced a Proxy Target
at all. The column is included because it is the strongest predictor available and excluding it
would be its own distortion, but a report calling the result "Amplification" would be
overclaiming, and CONTEXT.md's definition is specific.

**2. Training on a reanalysis and serving on a forecast is a second skew, and ADR 0004 only
anticipated the first.** (Since recorded as a consequence in ADR 0011, and handled by #13.) The
ADR separates the physical relationship from forecast error and
handles the latter in #14. But `analysis/overlap/` measured that IBI's swell **period** reads
systematically high against the operational feed the running system reads — by enough that #39
had to refit the thresholds rather than carry them across. A model fitted on IBI periods and
served Open-Meteo periods sees a shifted input distribution on a variable the Decision Model
leans on, and perturbing by a Forecast Error Profile does not correct an offset between two
different products. Either the offset is measured and applied, or the model is fitted on
features that do not carry it. Neither is done here, and #13 should not assume the ADR covers
it.

**3. Whether the pairing should be hourly at all.** Rows are hourly because both sources are,
but the thing being predicted is a *day* worth committing to travel for, and consecutive hours
are heavily autocorrelated. 73,601 rows is not 73,601 independent observations, and a
train/test split made on rows rather than on seasons would leak badly. The dataset is built at
the finest available grain so that #13 can aggregate; it is not a claim that hourly is the
right unit to fit on.

**4. Monican01 is present on 57.7% of rows, and nothing here says it earns its place.** It is
carried as an optional input on the strength of being a measurement rather than a model, not on
any measured contribution. If it does earn its place, the 42.3% of rows lacking it become a
second, smaller dataset rather than a flag to ignore.

**5. The Hindcast covers neither end of the buoy record, and could cover both.** #9 asks for
Hindcast conditions "covering the buoy's period". Monican02 begins 2010-06-12 and the cached
IBI download begins 2011-01-01, so **2,215 hours of Proxy Target have no Hindcast to pair
with** — three quarters of all unpaired hours, and it costs the 2010/11 Big-Wave Season most of
its October to December. At the far end the buoy runs to 2026-06-30 while IBI stops 2026-04-21,
costing a further **750 hours**. Together that is all 2,965 unpaired hours: every one is a
range mismatch, and none is a hole in the middle of the record.

This is a download range, not a limit of the product: #36 established IBI carries a Swell
partition back to 1980. `reanalysis.START` is set to 2011-01-01 because it matches
`hindcast.START` and the first Gold Day is 2011-11-01, which is the right bound for the
*backtest* that module was written for and the wrong one for training. Extending it means a
re-download with Copernicus credentials and would shift the backtest's span too, so it is
recorded here rather than changed underneath #11.

## Files

| File | What it is |
|---|---|
| `build.py` | The build. `--check` self-tests the join, the gap rule and the byte-stability offline. |
| `output/coverage_by_season.csv` | Per season: what each source offered, what paired, what fell inside the Big-Wave Season, and the target's distribution. |
| `output/training_dataset.csv` | The dataset. Gitignored; rebuilt by the command above. |
