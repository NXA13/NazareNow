# Calibrating the Decision Model's thresholds

Ticket #12. #11 established the benchmark and found what was wrong with it. This chooses the
numbers, and writes them where the running system reads them.

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
| Maximum wind speed | 35 km/h | unchanged |

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
written down as one in `GO_CALLS_PER_SEASON_BUDGET`, and it is the only hand-chosen number
left in the calibration.

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
| Significant Wave Height | 3.84-5.68 m | ≥ 3.75 m | no |
| Swell direction | 316-327° | 255-330° | no |
| Wind | calmest hour 2-7 km/h | offshore 20-180°, ≤ 35 km/h | no |

Fitting an arc to six Gold Days would narrow it onto noise while changing no call — the
observed directions span 11°, and an arc fitted to them would reject three quarters of the arc
the canyon is actually fed from. `calibrate.py` **raises** if any of the three turns out to
block a Gold Day, because at that point the claim this section rests on is false and the
calibration would need redoing rather than reporting.

The height bar is the one exception: it *is* derived, as the tightest bar admitting every Gold
Day in the fitting split, floored to 0.25 m. It rose from 3.0 m to 3.75 m and still does not
bind — the smallest Gold Day peak in the fitting split is 3.84 m.

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
