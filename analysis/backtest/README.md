# Backtesting the Heuristic Baseline

Ticket #11. The benchmark every later Amplification Model must beat, per ADR 0006.

> **Re-run after #12.** This report scores whatever thresholds the system currently ships, and
> #12 replaced them with values fitted to the Gold Days. The numbers below are therefore the
> *calibrated* rule's, not the rule of thumb's. Where the pre-#12 figure is worth keeping — the
> headline, and the two findings that drove #12 — it is shown beside the current one.
> `analysis/calibration/` is where the thresholds come from and why.

Reproduce with, from the repository root:

```bash
.venv/Scripts/python.exe analysis/backtest/hindcast.py    # fetches and caches the Hindcast
cd analysis/backtest && ../../.venv/Scripts/python.exe backtest.py
```

No credentials. The first command downloads about 10 MB from Open-Meteo into
`data/raw/hindcast/` (gitignored) and is skipped on later runs. Tables land in `output/`.

## The headline

**Scored against the four seasons where the Swell partition genuinely exists, the calibrated
Heuristic Baseline catches every one of the 9 Gold Days at Watch, 7 of 9 at Go Call, and
issues 16 Go Calls in four years.**

| Panel | Span | Days | Gold Days | Watch or better | Go Call | Go Calls issued | Of those, known Gold Days |
|---|---|---|---|---|---|---|---|
| **Operational** | 2022-2025 | 1,461 | 9 | 9/9 (100%) | 7/9 (78%) | 16 | 7 (≥44%) |
| Reconstructed | 2011-2021 | 4,018 | 29 | 13/29 (45%) | 7/29 (24%) | 37 | 7 (≥19%) |

Before #12 the same panel scored 3/9 at both tiers on 5 Go Calls. Recall was the problem the
backtest identified and recall is what moved; the price is that the Go Call tier now speaks
about four times a season instead of one, and a smaller share of what it says lands on a day
somebody documented.

The operational panel is the benchmark. The reconstructed panel is an indication, and the
next section says why it is weaker. Note that the operational panel is **partly in-sample**
since #12 — two of its four seasons are the ones the thresholds were fitted on.
`analysis/calibration/` reports the held-out split, which is the number to trust.

## One threshold caused the entire miss

This is the finding that drove #12, recorded as it stood against the rule of thumb.

Of the 6 Gold Days in the operational panel that earned no call at all, **swell period below
14 s was the blocking condition on all 6**. Not one of them failed on height, direction or
wind while clearing period.

The sweep below is scored against the current calibration, varying only the Go Call bar, so
its counts differ from the pre-#12 run — the height bar moved to 3.75 m at the same time:

| Go Call bar | Gold Days called | Go Calls issued in four years |
|---|---|---|
| 10 s | 9/9 | 60 |
| 11 s | 9/9 | 47 |
| 12 s | 9/9 | 33 |
| **13 s — shipped** | **7/9** | **16** |
| 14 s | 3/9 | 5 |
| 15 s | 0/9 | 1 |

The bar sits on a cliff, which is why it was worth fitting rather than guessing: one second
either side roughly halves or doubles what the tier says.

This table is **diagnostic, not the calibration** — it has seen every Gold Day, so it cannot
also validate against them. `analysis/calibration/` chooses the values on the fitting split
alone, with 2024-2025 kept back.

The clearest illustration of the original problem is that the misses were *bigger* than the
hits. 2022-02-25 (Hs 5.68 m) and 2025-12-13 (Hs 5.62 m) were missed while 2022-02-09 (Hs
3.84 m) earned a Go Call. Height was never the constraint. Both now earn a Go Call.

## The Watch tier adds recall again

ADR 0003 makes a Watch recall-optimised and a Go Call precision-optimised, and the two are
meant not to be one rule with two names. Against the rule of thumb they nearly were:

- Watch or better flagged **11** days; Go Call flagged **5**.
- Both caught **the same 3 Gold Days**. The extra 6 days a Watch bought contained no Gold Day.

A Watch dropped only the wind condition, and wind is not what blocks these days — period is.
So until the period threshold moved, the recall tier delivered no recall.

#12 gave the tiers **different period bars**, 12.5 s against 13 s, which is the fix. On this
panel a Watch now catches 9/9 where a Go Call catches 7/9: 2022-02-26 (Hs 5.02 m) and
2024-01-22 (Hs 4.58 m) are surfaced by the recall tier and withheld by the precision tier,
which is the trade ADR 0003 asks for.

## Precision here is a lower bound, and must be read as one

A Gold Day is a day somebody **documented** — a contest ran, a record was ratified, a
photographer was present. `gold_days/` is not a labelled record of every day Praia do Norte
went giant, and it does not claim to be.

So a flagged day that is not a Gold Day is not thereby a false Go Call. Among the sixteen Go
Calls in the operational panel are 2025-12-08 and 2025-12-18 — December days with Hs of
4.56 m and 5.14 m, sitting either side of the 2025-12-13 Gold Day, in the most recent season
the research covers. Whether they were XXL Days is unknown, not settled in the negative.

The honest figure is therefore **"at least 7 of 16"**, and the tables say
`precision_lower_bound` rather than `precision` for that reason. Reporting it as precision
would understate the rule and would let a later model score well by fitting who happened to be
holding a camera.

This is also why #12 calibrated the Go Call tier against a stated *call budget* rather than
against a precision figure. Optimising the number above would have optimised against who was
carrying a camera in 2022.

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

Scored at the shipped Go Call bar, which #12 moved from 14 s to 13 s — so these differ from
the figures the pre-#12 report carried:

| Reconstructed variable | Method | Held-out result |
|---|---|---|
| Swell period | quantile map from ERA5 **peak** period | RMSE 1.04 s; at the 13 s bar, recall 41%, precision 50% |
| Swell period *(rejected)* | quantile map from ERA5 mean period | RMSE 1.16 s; at 13 s, recall 41%, precision 39% |
| Swell direction | constant bearing offset, −2.0° | 80% of hours within 15° |
| Significant Wave Height | **not reconstructed** | ERA5's `wave_height` is already the variable the pipeline reads |

Peak period remains the better predictor, but by a narrower margin than at 14 s, where mean
period recovered no threshold crossing at all. At 13 s the two match on recall and peak period
wins on precision. It also wins on RMSE at every bar, which is the reason to prefer it that
does not depend on where the bar happens to sit.

Quantile mapping rather than regression because least squares fits a conditional mean, and a
conditional mean shrinks the tail that is the only part anyone cares about: fitted as a
regression, `swell period ~ mean period` predicted 22 hours at or above 14 s where the truth
had 95. (Measured at the pre-#12 bar and not re-run; the argument is about conditional means,
not about 14 s.)

**The period reconstruction is still not good enough to carry a verdict.** Recovering 41% of
threshold crossings means the pre-2022 panel's period condition is dominated by reconstruction
error rather than by the rule, and that is why its numbers are reported separately and called
an indication. The clearest evidence is the recall gap between the panels: 7 of 29 Gold Days
called at Go Call on reconstructed Swell against 7 of 9 on the real thing. The two panels are
looking at the same rule and the same ocean, so that gap is the reconstruction.

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

## What was tuned on the dates it scores, and what was not

This section inverted at #12, and the change is the most important caveat on the page.

- **The operational panel is now partly in-sample.** The thresholds were fitted on 2022-2023,
  which is half of it. Its 9/9 and 7/9 are therefore optimistic. `analysis/calibration/`
  reports the held-out 2024-2025 split — 3/3 at Watch and 2/3 at Go Call — and that is the
  number any accuracy claim should quote.
- The reconstruction is fitted on 2022-2023 and applied to 2011-2021 — disjoint years.
- Its validation is on 2024-2025, which the fit never saw.
- The reconstructed panel is out-of-sample for the thresholds, being entirely pre-2022. Its
  weakness is the reconstruction, not the fit.

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
