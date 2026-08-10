# Calibrating the Decision Model's thresholds

Ticket #12. #11 established the benchmark and found what was wrong with it. This chooses the
numbers, and writes them where the running system reads them.

> ## Superseded: refitted on 38 Gold Days by #39 and #40, and repriced by #43
>
> Everything from "The headline" down describes the fit on **9 Gold Days**, which was all the
> Swell record reached at the time. It is kept as the record of where the numbers came from.
> The shipped values are no longer these.
>
> | | #12 (9 Gold Days) | #39/#40 (38 Gold Days) | now (#43, #51, #60) |
> |---|---|---|---|
> | `minimum_significant_wave_height_m` | 3.75 | 2.75 | **2.75** |
> | `watch_minimum_swell_period_s` | 12.5 | 10.1 | **11.4** |
> | `go_call_minimum_swell_period_s` | 13.0 | 12.9 | **12.9** |
> | `light_wind_exemption_kmh` | — | 16.5 (new, ADR 0009) | **14.5** |
>
> The Watch row moved a second time without being refitted. #43 set it at 11.5; #60 changed which
> hours the swell period Translation is fitted on, and the *restated* bar became 11.4. The fitted
> value is still 12 s in reanalysis units, as it was after #43.
>
> The exemption is the one row that moved without being refitted: #51 found it was shipping in
> ERA5 units into a system that reads a forecast product, and translated it. The fitted value is
> still 16.5 km/h.
> | fitted on | 2021/22–2022/23, 6 Gold Days | 2011/12–2019/20, 25 | **25** |
> | validated on | 2023/24–2025/26, 3 Gold Days | 2020/21–2025/26, 13 | **13** |
>
> ### #43: the Watch tier now has a price, and it is the only thing that moved
>
> The open question this file recorded at the bottom of the #39/#40 block — whether "full recall
> on the fitting split" is the right way to choose the Watch bar — was answered no. **ADR 0010**
> replaces it with a budget, mirroring the Go Call bar: the Watch bar is the *lowest* period
> whose Watch rate stays within **40 Watch days per Big-Wave Season**. Recall is no longer a
> constraint on it.
>
> | Split | Tier | Recall before | Recall now | Days/season before | Days/season now |
> |---|---|---|---|---|---|
> | Fitting | Watch or better | 25/25 | **21/25** | 72.9 | **35.1** |
> | **Held-out** | **Watch or better** | **12/13** | **12/13** | **61.2** | **32.2** |
> | Fitting | Go Call | 10/25 | 10/25 | 7.2 | 7.2 |
> | Held-out | Go Call | 9/13 | 9/13 | 7.2 | 7.2 |
>
> **The held-out row is the whole argument.** Halving what the Watch tier costs changes its
> held-out recall by nothing at all — held-out recall is 12/13 at every bar from 12.0 s down to
> 10.0 s in the fit's units. The four Gold Days the old rule bought were bought in-sample only,
> at about 13 Watch days a season each, and a Watch that covered 35% of the Big-Wave Season is
> not a warning. ADR 0010 has the sweep, the alternatives that were rejected, and the
> sensitivity of the budget.
>
> The Go Call rows are identical either side. That is the check that this changed one tier.
>
> **The first re-run did not complete, and that was the finding.** On 25 fitting Gold Days the
> wind condition blocked six, so this calibration's central claim — that swell period is the
> only condition the evidence can distinguish, in
> "[Only swell period is fitted per tier](#only-swell-period-is-fitted-per-tier)" below — is
> false on the full record. It was the offshore arc rather than the speed: 2013-10-28,
> 2015-10-27, 2017-02-28, 2018-02-11, 2019-11-13 and 2020-02-17 had calmest-hour winds of
> **4–16 km/h**, far under the 35 km/h cap, from bearings of 225–346°. <!--fixed:#39--> ADR 0009 fixed it by
> exempting light winds from the arc, and the exemption is itself fitted here — 16.5 km/h, the
> lowest value admitting all six.
>
> **Fitted on the reanalysis, shipped in Open-Meteo units.** The fit runs on the Copernicus IBI
> series, where the same sea reads about half a second longer than the live feed reports. The
> three wave bars are translated on the way out, and since #51 so is the wind exemption — it is
> fitted against ERA5 and applied by a Pipeline Run to a forecast product that reads about
> 1.5 km/h lighter, so 16.5 km/h ships as **14.5**. `analysis/overlap/README.md` measures the
> wave transform and `analysis/wind_products/README.md` the wind one.
>
> **What it costs.** Recall went from 16 of 38 Gold Days at Watch to **37 of 38**, and Go Calls
> from 9 of 38 to 16. The Watch tier is much noisier for it: 1050 Watch days over the record
> against 106 before, roughly 70 a season. That is the recall tier behaving as ADR 0003 asks —
> "missing a forming swell is worse than raising a Watch that fades" — but it is a different
> product experience and worth seeing before it ships. Go Calls run at about 8.5 a season
> against a stated budget of 8, slightly over because the budget is enforced on the fitting
> split only.
>
> **The bars are far more permissive than #12's, and that is the honest consequence of full
> recall over 25 Gold Days rather than 6.** A Watch bar that has to catch every Gold Day in the
> fitting split lands wherever the least impressive of them sits. Whether "full recall on the
> fitting split" is still the right rule for choosing that bar is a fair question this fit does
> not answer — it is the same class of assumption as the wind condition, and it has not been
> re-examined. **#43 is where it got re-examined**, filed out of #40's review with this fit's
> own numbers: the 25th Gold Day costs about 14 Watch days a season at the margin, and the bar
> chosen for full recall on the fitting split scores 12/13 held out anyway. The answer was ADR
> 0010 and the section above; the numbers in this block are the ones it replaced.

Reproduce with, from the repository root:

```bash
.venv/Scripts/python.exe analysis/backtest/hindcast.py    # fetches and caches the Hindcast
.venv/Scripts/python.exe analysis/calibration/calibrate.py
.venv/Scripts/python.exe analysis/calibration/calibrate.py --check   # the arithmetic, offline
```

No credentials. The fit writes `backend/src/nazarenow/thresholds.json` — the file the Decision
Model loads — and its tables to `output/`.

## The headline

**Fitted on the 2021/22 and 2022/23 seasons and scored on 2023/24 through 2025/26, which the
fit never saw, the calibrated rule catches every Gold Day at Watch and two of three at Go
Call, issuing two Go Calls a season.**

| Split | Seasons | Gold Days | Tier | Recall | Days flagged | Per season | Precision (lower bound) |
|---|---|---|---|---|---|---|---|
| Fitting | 2021/22-2022/23 | 6 | Watch or better | **6/6** | 21 | 10.5 | ≥29% |
| Fitting | 2021/22-2022/23 | 6 | Go Call | 5/6 | 10 | 5.0 | ≥50% |
| **Held-out** | **2023/24-2025/26** | **3** | **Watch or better** | **3/3** | 23 | 7.7 | ≥13% |
| **Held-out** | **2023/24-2025/26** | **3** | **Go Call** | **2/3** | 6 | 2.0 | ≥33% |

The held-out rows are the ones that mean anything. They are also **three Gold Days wide**, and
no amount of care in the method fixes that — see "What this rests on" below.

**The split falls on Big-Wave Season boundaries, not calendar years.** CONTEXT.md defines a
season as October through March and warns that splitting one across two calendar years
destroys the unit. An earlier version of this fit split on 2022-2023 against 2024-2025, which
cut the 2023/24 season in half: its autumn went to the fitting split and its winter to the
held-out one. The held-out split was then not held out, and `Split.seasons` counted 2023/24
twice, inflating the denominator of the very rate the Go Call budget is checked against.
Fixing it did not move either threshold — all six fitting Gold Days fall in 2021/22 — but it
moved the reported per-season rates, which is why they differ from the numbers in the first
commit. `calibrate.py` now raises if the two season lists intersect.

### The held-out split is the better-evidenced half

`gold_days.jsonl` records how each Gold Day is known. It turns out all three held-out Gold
Days are **buoy-measured** — an instrument recorded the size — while all six fitting Gold Days
are `unknown`, attested by report rather than measurement.

| Split | Tier | Buoy-measured Gold Days called |
|---|---|---|
| Fitting | either | none in this split |
| Held-out | Watch or better | 3/3 |
| Held-out | Go Call | 2/3 |

That is a good accident rather than a design: the thresholds were chosen against days
somebody documented and checked against days something measured. It is also why the held-out
recall figures are worth more than their sample size alone suggests, and it is the separate
reporting of the buoy-measured subset that #12's brief asked for.

## What the thresholds are

| | Before #12 | After |
|---|---|---|
| Minimum Significant Wave Height | 3.0 m | **3.75 m** |
| Minimum swell period — Watch | 14 s | **12.5 s** |
| Minimum swell period — Go Call | 14 s | **13 s** |
| Swell arc | 255-330° | unchanged |
| Offshore wind arc | 20-180° | unchanged |
| Maximum wind speed | 35 km/h <!--now:maximum_wind_speed_kmh--> | unchanged |

They live in `backend/src/nazarenow/thresholds.json`, not in code. `NAZARENOW_THRESHOLDS`
points the running system at a different file, so recalibrating does not mean redeploying —
and each Pipeline Run rereads it, so a new calibration takes effect on the next run.

## Scored across the whole operational panel

The table above is the honest one, because the held-out split is the only part the fit never
saw. But #11's benchmark was reported over all four seasons at once, so here is the same
comparison on that footing — the *combined* fitting and held-out record, which is partly
in-sample and reads better than it should:

| | Before #12 | After | |
|---|---|---|---|
| Gold Days caught at Watch or better | 3/9 | **9/9** | every one |
| Gold Days caught at Go Call | 3/9 | **7/9** | |
| Go Calls issued in four years | 5 | 16 | 4 a season |
| Go Call precision (lower bound) | ≥60% | ≥44% | fewer of them are known Gold Days |

Recall was the problem #11 identified, and recall is what moved. The cost is real and stated:
the Go Call tier speaks three times as often and a smaller share of what it says lands on a
day somebody documented.

## How the numbers were chosen

Two rules, one per tier, matching what ADR 0003 says each tier is for.

**The Watch bar is the highest swell period that still catches every Gold Day in the fitting
split.** Recall is the constraint; among the bars achieving it, the highest flags fewest days.
Taking the lowest instead would score identical recall while burying it in noise.

> **Replaced by ADR 0010.** Both bars are now chosen the same way — the lowest period the tier
> can afford against a stated budget — and the Watch tier's budget is 40 days a Big-Wave
> Season. The rule described in the paragraph above is the one #43 removed; the paragraph
> below, on the Go Call bar, still stands.

**The Go Call bar is the lowest swell period whose Go Call rate stays inside a stated budget
of eight per Big-Wave Season**, and which sits strictly above the Watch bar. Recall falls as
the bar rises, so the lowest affordable bar catches most Gold Days without exceeding what a Go
Call may cost the person receiving it.

### Why a call budget rather than a precision target

Precision against Gold Days is only ever a **lower bound**. A Gold Day is a day somebody
documented — a contest ran, a record was ratified, a photographer was there. A flagged day
that is not on the list is not thereby a false positive; it may be an XXL Day nobody
photographed. Optimising a precision *number* would therefore optimise against who happened to
be holding a camera, which is the failure #11 warned about and ADR 0006 forbids.

What can be stated honestly is what a Go Call costs its recipient: it says book travel to
Portugal. Eight per season is roughly one every three weeks. That is a product judgement,
written down as one in `GO_CALLS_PER_SEASON_BUDGET`.

It was the only hand-chosen number left in the calibration until #43, which gave the Watch tier
the same treatment for the same reason: `WATCH_DAYS_PER_SEASON_BUDGET`, 40 days a Big-Wave
Season, argued in ADR 0010. There are two now, both product judgements, both stated as such.

### The budget did not actually bind, and that matters

Every bar from 12.5 s up is inside eight calls a season. So the budget is slack, and what
actually held the Go bar up was **having to sit above the Watch bar**. The record does not
distinguish 13 s from 13.5 s or 14 s on the precision side; 13 s was taken because it is the
lowest of those, and lower means more Gold Days caught.

Read that as a limitation, not a subtlety. The Watch bar is pinned by the evidence. The Go
Call bar is pinned by the Watch bar plus one step of the sweep, and a different budget or a
finer sweep would move it. The threshold file's own `method` field says so, so the claim
travels with the number instead of living only here.

## Only swell period is fitted per tier

#11 measured that period blocked all six missed Gold Days and that height, direction and wind
blocked none. So period is the only condition the evidence can tell apart, and the only place
a recall tier and a precision tier can genuinely differ.

The other three are **verified rather than fitted** — checked to admit every Gold Day in the
fitting split, with the observed range reported:

| Condition | Observed across Gold Days | Threshold | Binds? |
|---|---|---|---|
| Significant Wave Height | 2.98-5.90 m | ≥ 2.75 m <!--now:minimum_significant_wave_height_m--> | no |
| Swell direction | 287-331° | 255-330° | no |
| Wind | calmest hour 0-21 km/h | ≤ 16.5 km/h, or offshore 20-180° and ≤ 35 km/h <!--now:maximum_wind_speed_kmh--> | no |

The bars in this table are the ones the fit chooses, in the reanalysis units it runs in — the
same numbers `calibrate.py` prints. `thresholds.json` ships them translated into Open-Meteo
units, which is a separate step and can move them.

"Binds? no" means no Gold Day was *blocked*, not that every Gold Day's whole range sits inside
the bar: a day is admitted on its best matching hour, which is why the observed direction range
can reach past the arc's edge and still cost nothing. `calibrate.py` **raises** if any of the
three turns out to block a Gold Day, because at that point the claim this section rests on is
false and the calibration would need redoing rather than reporting.

Fitting an arc to the Gold Days would narrow it onto noise while changing no call — an arc
fitted to the observed 44° would reject most of the arc the canyon is actually fed from.

The height bar is the one exception: it *is* derived, as the tightest bar admitting every Gold
Day in the fitting split, floored to 0.25 m. At 2.75 m <!--now:minimum_significant_wave_height_m--> it still does not bind — the smallest
Gold Day peak in the fitting split is 2.98 m.

Ticket #15 now prices a second rule against this same margin. The Go Call confidence floor asks
how sure the forecast is that a day clears this bar, and the gap between the bar and that
smallest Gold Day is the band it is allowed to refuse in — see
`analysis/forecast_error/README.md`, finding 5.

## The Watch tier now adds recall

#11's second finding was that the Watch tier was decorative: it flagged 11 days to the Go
Call's 5 and caught the *same* three Gold Days, because it dropped only the wind condition and
wind never blocked a Gold Day. ADR 0003 asks the two tiers to trade differently, and they did
not.

They do now. Across the operational panel a Watch catches **9/9** Gold Days where a Go Call
catches **7/9** — so there are two days the recall tier surfaces and the precision tier will
not, which is exactly the trade the ADR describes. On the held-out split alone it is 3/3
against 2/3.

Concretely, 2022-02-26 (Hs 5.02 m) and 2024-01-22 (Hs 4.58 m) earn a Watch and not a Go Call.

## What this rests on

**Nine Gold Days.** Six to fit, three to check. Real Swell measurements begin around 2022 and
the reconstruction back to 2011 recovers only 16% of threshold crossings (#11), so the other
29 Gold Days in `gold_days/` cannot be used here. Issue #36 asks whether Copernicus WAVERYS
can extend that record back to 1993; until it is answered, nine is the ceiling.

Three held-out Gold Days cannot distinguish a good calibration from a lucky one. A single day
falling the other way moves held-out Go Call recall from 2/3 to 1/3. The interface states the
number to the user for this reason, and any accuracy claim made from these thresholds has to
carry it too — ADR 0006 requires exactly that.

**The split is chronological**, fitted on the 2021/22 and 2022/23 seasons and validated on
2023/24 onward — the same direction the system runs in: fit on the past, apply to the future.
Nothing here was tuned on the seasons it reports. #11's swell reconstruction splits the same
record on calendar years rather than seasons; that is a fit over hourly pairs, where a season
is not the meaningful unit, so it was left as it is.

**These are Hindcast numbers.** A Hindcast is what the ocean did, not what a forecast said it
would do, so this scores the rule given perfect knowledge of Offshore Conditions — its
ceiling. Real Go Calls are issued days ahead from a forecast wrong by an amount #14 measures,
and will do worse.

## Files

| File | What it is |
|---|---|
| `calibrate.py` | The fit. `--check` self-tests the two selection rules offline. |
| `output/period_sweep.csv` | Every candidate period, scored as a Watch bar and as a Go Call bar. |
| `output/calibrated_scores.csv` | Recall and precision-lower-bound per tier, per split. |
| `../../backend/src/nazarenow/thresholds.json` | What the fit produced, and what the system reads. |

Like the backtest, this is **not** wired into the automated test suite: an assertion that
fails when accuracy shifts slightly gets disabled within weeks. What `backend/tests/
test_baseline_is_fixed.py` pins instead is the shipped threshold file itself, so this report
cannot silently stop describing the rule it names.
