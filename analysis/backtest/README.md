# Backtesting the Heuristic Baseline

Ticket #11. The benchmark every later Amplification Model must beat, per ADR 0006.

Reproduce with, from the repository root:

```bash
.venv/Scripts/python.exe analysis/backtest/hindcast.py    # fetches and caches the Hindcast
cd analysis/backtest && ../../.venv/Scripts/python.exe backtest.py
```

No credentials. The first command downloads about 10 MB from Open-Meteo into
`data/raw/hindcast/` (gitignored) and is skipped on later runs. Tables land in `output/`.

## The headline

**Scored against the four seasons where the Swell partition genuinely exists, the Heuristic
Baseline catches 3 of 9 Gold Days and issues 5 Go Calls in four years.**

| Panel | Span | Days | Gold Days | Watch or better | Go Call | Go Calls issued | Of those, known Gold Days |
|---|---|---|---|---|---|---|---|
| **Operational** | 2022-2025 | 1,461 | 9 | 3/9 (33%) | 3/9 (33%) | 5 | 3 (≥60%) |
| Reconstructed | 2011-2021 | 4,018 | 29 | 6/29 (21%) | 4/29 (14%) | 21 | 4 (≥19%) |

The operational panel is the benchmark. The reconstructed panel is an indication, and the
next section says why it is weaker.

**Recall is the problem, not precision.** The rule almost never speaks — five Go Calls in
four years, about one and a quarter per season — and when it does it is right more often
than not. It misses two thirds of the days someone actually rode.

## One threshold causes the entire miss

Of the 6 Gold Days in the operational panel that earned no call at all, **swell period below
14 s was the blocking condition on all 6**. Not one of them failed on height, direction or
wind while clearing period.

| Threshold | Gold Days called | Go Calls issued in four years |
|---|---|---|
| 10 s | 9/9 | 138 |
| 11 s | 9/9 | 96 |
| 12 s | 9/9 | 57 |
| 13 s | 7/9 | 20 |
| **14 s — shipped** | **3/9** | **5** |
| 15 s | 0/9 | 2 |

`MINIMUM_SWELL_PERIOD_S = 14.0` sits on a cliff. One second lower more than doubles recall;
two seconds lower catches every Gold Day in the span at fourteen Go Calls a year.

This table is **diagnostic, not a calibration** — it exists because the backtest raised the
question, and picking a value is #12's job, against a held-out split and a stated precision
target. Nothing here changes what the system ships.

The clearest illustration is that the misses are *bigger* than the hits. 2022-02-25 (Hs
5.68 m) and 2025-12-13 (Hs 5.62 m) were missed; 2022-02-09 (Hs 3.84 m) earned a Go Call.
Height was never the constraint.

## The Watch tier currently adds nothing

ADR 0003 makes a Watch recall-optimised and a Go Call precision-optimised, and the two are
meant not to be one rule with two names. On this record they nearly are:

- Watch or better flags **11** days; Go Call flags **5**.
- Both catch **the same 3 Gold Days**. The extra 6 days a Watch buys contain no Gold Day at all.

A Watch drops only the wind condition (`WATCH_CONDITIONS` in `decision.py`), and wind is not
what blocks these days — period is. Until the period threshold moves, the recall tier
delivers no recall. Worth carrying into #12, which owns both thresholds.

## Precision here is a lower bound, and must be read as one

A Gold Day is a day somebody **documented** — a contest ran, a record was ratified, a
photographer was present. `gold_days/` is not a labelled record of every day Praia do Norte
went giant, and it does not claim to be.

So a flagged day that is not a Gold Day is not thereby a false Go Call. Two of the five Go
Calls in the operational panel are 2025-12-08 and 2025-12-18 — December days with Hs of
4.56 m and 5.14 m, sitting either side of the 2025-12-13 Gold Day, in the most recent season
the research covers. Whether they were XXL Days is unknown, not settled in the negative.

The honest figure is therefore **"at least 3 of 5"**, and the tables say `precision_lower_bound`
rather than `precision` for that reason. Reporting it as precision would understate the rule
and would let a later model score well by fitting who happened to be holding a camera.

## Why there are two panels

The Hindcast is not uniform, and the join is where a benchmark could quietly become fiction.

`era5_ocean` reaches back to 2011 but describes the **Combined Sea** only — it returns null
for every `swell_wave_*` variable. The operational models carrying the **Swell** partition,
which is what the live Pipeline Run reads and what the rule's thresholds are written in,
begin around 2022:

| Model | Swell partition reaches back to |
|---|---|
| `era5_ocean` | never — Combined Sea only, but 2011+ |
| `best_match` (= `meteofrance_wave` here) | ~2022 |
| `dwd_ewam` | ~2023 |
| `ncep_gfswave025` | ~2025 |

CONTEXT.md holds Combined Sea and Swell apart, and this is exactly where conflating them
would do damage: both have a variable called "period", and scoring a Swell threshold against
a Combined Sea number because the names match would produce a rigorous-looking benchmark of
the wrong quantity.

So the pre-2022 record is scored on **reconstructed** Swell, and the reconstruction is
measured rather than assumed.

### What the reconstruction is worth

Fitted on the 2022-2023 overlap (17,520 hours), validated on 2024-2025 (7,753 hours) — years
the fit never saw.

| Reconstructed variable | Method | Held-out result |
|---|---|---|
| Swell period | quantile map from ERA5 **peak** period | RMSE 1.04 s; at the 14 s threshold, recall 16%, precision 33% |
| Swell period *(rejected)* | quantile map from ERA5 mean period | RMSE 1.16 s; at 14 s, recall 0% — predicts no crossing at all |
| Swell direction | constant bearing offset, −2.0° | 80% of hours within 15° |
| Significant Wave Height | **not reconstructed** | ERA5's `wave_height` is already the variable the pipeline reads |

Quantile mapping rather than regression because least squares fits a conditional mean, and a
conditional mean shrinks the tail that is the only part anyone cares about: fitted as a
regression, `swell period ~ mean period` predicts 22 hours at or above 14 s where the truth
has 95.

**The period reconstruction is not good enough to carry a verdict.** Recovering 16% of
threshold crossings means the pre-2022 panel's period condition is dominated by
reconstruction error rather than by the rule, and that is why its numbers are reported
separately and called an indication. Its inflated Go Call rate — 21 calls over 4,018 days
against 5 over 1,461 — is largely the reconstruction, not the ocean.

## Two grid caveats

The three series do not sample the same point:

| Series | Grid | Distance from the Proxy Target |
|---|---|---|
| Operational Swell | 39.5417, −9.2083 | 2 km |
| ERA5 wind | 39.5431, −9.0997 | 9.6 km ESE, close inshore |
| ERA5 Combined Sea | 39.5000, −9.5000 | **25.7 km WSW** — the model runs on a 0.5° grid |

The ERA5 wind point sits near enough to the coast that its speed and direction are affected
by land, which matters for a rule with an offshore-wind condition. The Combined Sea point is
far enough out that some of the reconstruction's error is simply distance. Neither is fatal;
both belong in the record.

One more, found the hard way: ERA5 stops carrying `wave_peak_period` after **2024-11**.
Requiring it alongside the other variables silently dropped two Gold Days — 2025-02-18 and
2025-12-13 lost all 24 hours each — so `hindcast.py` treats it as optional and
`backtest.py` refuses to score a panel whose Gold Days have lost hours.

## What this benchmark does not measure

A Hindcast is what the ocean did, not what a forecast said it would do. These numbers score
the *rule* given perfect knowledge of Offshore Conditions — its ceiling. A real Go Call is
issued days ahead from a forecast wrong by an amount #14 measures, and will do worse.

The scores are also not a Lead Time study. Every hour is scored at a Lead Time of 3 days,
chosen only because it falls inside both the Watch and the Go Call band so one pass yields
both tiers. The Heuristic Baseline's conditions do not vary with Lead Time; only the tier
names do.

## Nothing here was tuned on the dates it scores

- The baseline's thresholds are the surf community's rule of thumb, fitted to nothing. #12 is the ticket that changes that.
- The reconstruction is fitted on 2022-2023 and applied to 2011-2021 — disjoint years.
- Its validation is on 2024-2025, which the fit never saw.

## Files

| File | What it is |
|---|---|
| `hindcast.py` | Fetches and caches the three series. Validates units, timezone and completeness on arrival. |
| `swell.py` | The Combined Sea → Swell reconstruction and its scoring. `--check` self-tests the arithmetic. |
| `backtest.py` | Scores the real `HeuristicBaseline` and `decide`, writes the tables. |
| `output/summary.csv` | The headline table. |
| `output/daily_calls.csv` | Every scored day, its call, and whether it is a Gold Day. |
| `output/period_sensitivity.csv` | The threshold sweep. |

Per the ticket, this backtest is **not** wired into the automated test suite: a test that
fails when accuracy shifts slightly would be disabled within weeks and would block
legitimate experimentation. What is tested, in `backend/tests/test_baseline_is_fixed.py`, is
that the Heuristic Baseline returns a fixed result for fixed inputs — so this report cannot
silently stop describing the thing it names.
