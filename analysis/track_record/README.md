# The published track record

Ticket #16. `publish.py` assembles `backend/src/nazarenow/track_record.json` from the reports
that already measured the system, and the API serves it at `/api/track-record`.

```bash
# Regenerate the published file.
.venv/Scripts/python.exe analysis/track_record/publish.py

# Self-test every join, offline. No credentials, no download.
.venv/Scripts/python.exe analysis/track_record/publish.py --check
```

## It measures nothing

That is the design. Every figure the page shows is already committed somewhere in
`analysis/`, and a second calculation of the same number is a second answer — with the one on
the website being the one nobody re-derives. So this script joins and renames, and refuses
anything it does not recognise.

| Section | Source | Ticket |
|---|---|---|
| held-out call record | `analysis/calibration/output/calibrated_scores.csv` | #12 |
| whole-record call record | `analysis/backtest/output/summary.csv` | #11 |
| day-by-day record | `analysis/backtest/output/daily_calls.csv` | #11 |
| scored height accuracy | `analysis/amplification_model/output/held_out_scores.csv` | #13 |
| served height accuracy | `analysis/amplification_model/output/translation_shapes.csv` | #52 |
| range calibration | `analysis/distribution_coverage/output/interval_coverage.csv` | #80, #94 |
| Gold Day split | `backend/src/nazarenow/thresholds.json` | #12 |

## The served figures are #52's, not `served_path.py`'s

This is the one join where taking the obvious file would publish a wrong number, so it is
worth stating plainly.

`analysis/amplification_model/output/served_path_scores.csv` reconstructs the operational
series **using the shipped Translation** and then scores a model that inverts the same
Translation, so any error in the transform is partly measured against itself.

Until #58 that mattered a great deal. The shipped Translation extrapolated about +0.34 m below
the range it was fitted on and handed that error to the Heuristic Baseline as a free upward
shift, making its two most flattering rows artefacts of the transform under test:

| Held-out band | `served_path_scores.csv` | fair generator |
|---|---|---|
| all hours | +0.035 | **−0.077** |
| measured target under 2 m | +0.074 | **−0.126** |

Positive means the learned Amplification Model is closer to the Proxy Target. Published
unchecked, the page would have claimed the learned model beats the rule of thumb on ordinary
days, on the strength of an error the measurement was supposed to be independent of.

**#58 removed the distortion at its source** by refitting the height Translation on all 35,064
overlapping hours. The same two rows now read −0.014 and −0.033 from `served_path_scores.csv`
against −0.016 and −0.035 from the fair generator — a 0.002 m gap where there was a 0.11 m one.
The published figures are the fair-generator ones either way; the indirection is kept because
the guarantee should not depend on the two happening to agree.

What is taken instead is `translation_shapes.csv` filtered to the shipped candidate under the
`regime-aware` generator with a flat residual — the *fair generator* column of
`analysis/amplification_model/README.md`. `--check` pins both rows above, because reading the
wrong generator does not fail: it publishes eight plausible numbers, two of them wrong in the
direction that flatters.

## Two rows carry a caveat, because their sources insist

A figure that looks strong and is qualified is the kind a page drops on the way to a table,
so the qualification rides on the band rather than in the renderer.

| Row | Why |
|---|---|
| scored `Gold Day hours` | 120 hours across **5** Gold Days. `analysis/amplification_model/README.md`: "that is the number to hold this claim to". |
| served `Combined Sea 3 m and above` | **+0.027 becomes −0.004** under a residual grown with the sea — and it is the *shipped* fit that reverses, not an alternative. #52: do not quote this aggregate as robust to the reconstruction assumption. |

The served caveat's two numbers are read from `translation_shapes.csv`, so the warning cannot
drift from the figure it qualifies, and `--check` fails if the row arrives without it.

**The Gold Day count of 5 is the one figure typed here rather than joined.** It exists only in
the amplification README's prose — `held_out_scores.csv` carries hours, not distinct days — so
`--check` cannot verify it, and `GOLD_DAY_CAVEAT` cites its source instead. The alternative was
dropping the row, and it is the row #16 asks for most directly.

## The range calibration carries no verdict

#94. The site states an uncertainty range in metres and #80 measured whether it means what it
says. It does not: the range claims 90% and held the outcome 94.0% of the time one day ahead
and 99.4% seven days ahead, growing wider relative to the outcomes the further ahead it looks.

Every other figure this script publishes is scored against the **Gold Days**. This one is
scored against the sea, hour by hour, which makes it the broadest evidence on the page — and
the two caveats travelling with it are why that is not the licence it sounds like.

**What is published is the claim and the measurement. Never a direction.** Both directional
sentences on the page — which way the range misses, and whether the miss grows with Lead Time —
are derived where they are rendered, and the reason is
[#82](https://github.com/NXA13/NazareNow/issues/82): that ticket exists to narrow this
distribution, and a "too wide" verdict written into the record or into the page's copy would
survive the refit that made it false. The growth clause needs it most, since the growth *rate* is
what the repair is aimed at. The backend's parser is deliberately silent on direction too — it
refuses a subset larger than its superset and a share above one, and accepts coverage *below* the
claim, because that is #82 landing rather than a corrupt file.

**Both subsets travel on every Lead Time, as named fields.** The `big swell` rows cover the
bigger seas and read kinder than the whole (0.94 of the required half-width at one day, against
0.82). A shape able to carry one alone is a shape able to publish the kinder number under a
heading a reader takes for the whole finding — the rule `TIERS` already keeps.

**`big_swell_from_m` is published so the page need not type it**, and `--check` pins it against
`analysis/forecast_error/profile.py`'s `BIG_SWELL_M`, the constant `coverage.py` scores the
subset with. It is **not** the Go Call's height bar:
`thresholds.json` sets that at **2.75 m** <!--now:minimum_significant_wave_height_m-->,
and `analysis/distribution_coverage/README.md` is explicit that 3 m is an analysis choice drawn
"rather than at a Gold Day". A page describing this subset as the sea a Go Call is issued on
would state something false about the one number a reader is asked to spend money on — which is
the defect this section exists to end, not to commit again.

**Two caveats are typed here rather than joined**, following `GOLD_DAY_CAVEAT`. Both live only
in `analysis/distribution_coverage/README.md`'s prose, so `--check` cannot verify them:

| Caveat | Why it must travel |
|---|---|
| `RANGE_UNDERSTATES_BECAUSE` | Every distribution scored was built with `model_spread=None`, and `_drift_floor` only ever raises the drift. So the range the running system prints is **wider** than the one measured, and the table understates its own finding. |
| `RANGE_RESTS_ON` | 1,593 hours from 2025-11-26 to 2026-02-20, clustering into a few dozen swells, with a single confirmed giant day inside the window. A reader who takes "1,593 hours" as the sample size has the flattering half of a two-part fact. |

## Rates are not written

The file carries counts. `backend/src/nazarenow/track_record.py` divides.

A file holding both `days_flagged` and a `precision` holds the same fact twice, and the copies
drift in one predictable direction — the rate is what gets quoted, the counts are what get
regenerated. Making the rate a property means a recall the counts do not support cannot be
published at all.

The backend refuses the file outright on several arithmetic impossibilities: more Gold Days
caught than the panel contains, a Watch tier flagging fewer days than the Go Call tier, a
validated Gold Day count that is not the held-out panel's. Each of those parses cleanly and
inverts the meaning of a number a reader takes away.

## What `--check` pins

Offline, against the committed reports:

1. **The season counts.** `calibrate.py` published a per-season rate from its own split; this
   script counts Big-Wave Seasons from the day-by-day record instead. The two agreeing is what
   makes "flags per Big-Wave Season" on the page the same quantity #12 reported rather than
   the same words over a different divisor.
2. **The Gold Day split**, against `thresholds.json`. The held-out panel and the calibration's
   validated count have to be the same days.
3. **The served generator**, by pinning the two rows #52 moved.
4. **Both tiers surviving every join**, and the Watch tier being the broader one. A tier
   silently dropped leaves a page reporting one tier's figures under both headings, which is
   the shape of the collapse #12 exists to undo rather than a visible gap.
5. **The day-by-day union.** A Gold Day the system issued a Go Call for belongs to both sets,
   and a union built by concatenation would list it twice — doubling the most important rows.
6. **`summary.csv` against `daily_calls.csv`.** These are different files, and #11 regenerating
   one without the other is how a summary starts describing a backtest that has since moved.
7. **#52's warning is attached to the row it is about**, and to no other row. Spreading it
   would warn about figures that hold their sign under every assumption; dropping it would
   publish the one that does not as though it did.
8. **The range calibration**, in two kinds. The joins: both subsets present at every Lead Time,
   the big-swell hours no larger than the hours they are drawn from, no Lead Time skipped, the
   width rising as the forecast reaches further, and the published big-swell bar matching the
   constant the subset was scored at. And the direction: coverage at or above
   the claim, a widening factor under one, and that factor falling with Lead Time. The
   directional pins **will fail if #82 lands**, on purpose — the two caveats published beside
   the table are written for a range that runs wide, and a refit reversing the finding must not
   slip past with the old prose still attached. The failure message says so.
9. **The committed `track_record.json` is what this script would write now.** Everything else
   checks the joins and none of it looks at the output, so a report regenerated after the last
   publish leaves a stale record that every other check passes — and the stale record is what
   the backend serves. `published_at` is excluded from the comparison because it moves by
   design; everything else must match byte for byte.

## Two things it deliberately does not publish

**A live record.** Every panel is derived from the Hindcast, which is a reconstruction of
Offshore Conditions built after the fact and never available in advance. The API adds an
`issued` section counted from the store's retained calls, unscored — no buoy reading reaches
the running system, so there is nothing to score a stored call against. The page states this
above every figure rather than below them.

**A Gold Day row in the served table.** #52 measured the served path per band of sea state,
not per day, so `translation_shapes.csv` carries no Gold Day hours row. The scored table has
one; the served table does not, and the page does not silently reuse the scored figure to
fill the gap.
