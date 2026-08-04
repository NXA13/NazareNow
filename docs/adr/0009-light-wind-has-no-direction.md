# Light wind has no direction

The Heuristic Baseline's wind condition requires the wind to be inside the offshore arc **and**
at or below the speed cap, with no interaction between the two. A 4 km/h breeze from 225° fails
it exactly as a 35 km/h onshore gale does.

That is not what the rule of thumb means. Wind matters at Praia do Norte because it grooms or
wrecks the wave face. A wind too light to raise a ripple cannot wreck anything, whichever way it
happens to be blowing. The condition encodes "offshore and light" as a conjunction when the
underlying claim is a disjunction: **the wind is light enough not to matter, or it is offshore
and within the cap.**

We change the condition to say that, and we add an exemption speed below which direction is not
consulted. It is a fitted threshold living in `thresholds.json` beside the others, not a
constant in code.

## Why this is an ADR and not another amendment to ADR 0006

Ticket #12 fitted the baseline's numbers and recorded it as an amendment to ADR 0006, correctly:
moving 14 s to 13 s changes how strict the benchmark is, not what it is. A learned model still
has to beat the same shape of rule.

This is different. It changes the **shape**. A rule with a light-wind exemption is not the
community's rule of thumb tightened or loosened; it is a different predictor, and figures
measured against the old shape and the new one are not comparable. ADR 0006 makes the Heuristic
Baseline permanent precisely so that comparisons across time mean something, so altering it is
exactly the kind of decision that has to be argued in the open rather than folded into a
calibration.

## What forced it

Ticket #12 calibrated on 9 Gold Days, of which 6 were in the fitting split, and on those the
wind condition never bound. #39 ingested the Copernicus reanalysis and re-ran the fit against
38 Gold Days, 25 of them fitting. Six of those 25 are blocked by wind — every one by the arc,
none by the speed:

| Gold Day | Calmest hour | Bearing | Peak Hs |
|---|---|---|---|
| 2013-10-28 | 4.1 km/h | 225° | 4.20 m |
| 2015-10-27 | 8.4 km/h | 310° | 4.74 m |
| 2017-02-28 | 5.4 km/h | 323° | 5.56 m |
| 2018-02-11 | 5.9 km/h | 346° | 3.04 m |
| 2019-11-13 | 15.8 km/h | 339° | 4.33 m |
| 2020-02-17 | 16.3 km/h | 265° | 4.98 m |

The arc is 20–180° and the cap is 35 km/h. Every one of these days sits far under the cap and
outside the arc. These are documented XXL Days — contests run, records ratified — and the rule
that is supposed to describe them says they were unsurfable because of a breeze.

`analysis/calibration/calibrate.py` refuses to complete rather than fit around this, because
#12's calibration rests on the claim that swell period is the only condition the evidence can
distinguish, and on the full record that claim is false.

## What we rejected

**Widening the arc to admit those bearings.** It would fix the six days and let genuine onshore
wind through at any speed, which is the opposite failure and costs precision on exactly the days
a Go Call is expensive — a Go Call tells someone to book travel. The six days are evidence that
*4 km/h* is fine. They are not evidence that 225–346° is fine.

**Raising the speed cap.** The cap and the exemption are different quantities and conflating
them would break both. The cap is an upper bound on a *good* wind: offshore wind strong enough
to be a problem. The exemption is a lower bound on a wind that counts at all. Raising the cap to
16 km/h would do nothing for these days, because they fail on direction, and would loosen the
condition where it is currently working.

**Dropping the wind condition.** It blocks nothing else in the record, but that is an argument
for keeping a condition that is cheap and physically real, not for deleting it.

## Consequences

The benchmark's definition moves, so every accuracy figure recorded against the old wind
condition needs re-reading. The most recent is `analysis/backtest/README.md`: 16 of 38 Gold Days
at Watch or better. That is the last figure measured against the conjunction, and the figure
after this lands is not an improvement to it — it is a different measurement.

`thresholds.json` grows a field, and `thresholds.parse` must validate it and refuse a file that
omits it. Every other threshold is handled that way, and an exemption speed that silently
defaulted would be a condition changing shape based on a missing line.

`ConditionOutcome` now has two ways to hold and they are not the same statement to a user. "The
wind is too light to matter" and "the wind is offshore and light at 12 km/h" describe different
days, and the interface shows these sentences. `_wind_fault` has to follow the disjunction too,
or a day that failed will be told the wrong reason.

The exemption speed is fitted against the Gold Days rather than chosen, and the fit is reported
the way `analysis/calibration/` reports the others. The six days above put a floor under it at
16.3 km/h; the days that already pass put a ceiling on how far it can rise before it starts
admitting genuine onshore slop.

**Amended by #51: every speed on this page is an ERA5 speed, and the shipped bar is not.** The
days above are read from the ERA5 archive, which is what the fit sees. A Pipeline Run applies
the bar to Open-Meteo's forecast product, which reads about 1.5 km/h lighter in this band, so
the fitted 16.5 km/h ships as **14.5**. Nothing about the six days or the 16.3 km/h floor
changes — they are the same weather — but a reader comparing this page against
`thresholds.json` will find two different numbers, and this is why.

ADR 0006's requirement that the learned model and the Heuristic Baseline are reported side by
side is unaffected. Its amendment's second obligation — that any figure derived from the
calibration states how many Gold Days it rests on — now has a larger and more honest number to
state.

## What this does not settle

The six days come from the fitting split alone, 2011/12–2019/20. The calibration raises before
it scores the held-out half, so whether 2020/21–2025/26 holds more days in the same position is
not yet known and the fit will say when it runs.

Whether a single speed is the right shape for the exemption is assumed, not established. Wind
that matters is presumably a function of how it interacts with the face, and a hard cutoff is
the simplest thing that fixes the observed failure rather than the most defensible model of the
physics. If the fitted value turns out to sit in a region where the Gold Days give it no
support, that is worth saying rather than shipping a number the record does not pin down — the
same honesty ticket #12 applied to its Go Call bar.
