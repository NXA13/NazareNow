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
8. **The committed `track_record.json` is what this script would write now.** Everything else
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
