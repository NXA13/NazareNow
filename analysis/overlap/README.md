# What is Open-Meteo's Swell, in Copernicus terms?

Run `.venv/Scripts/python.exe analysis/overlap/measure.py` to reproduce; it needs the cached
reanalysis downloads, which `analysis/backtest/reanalysis.py` fetches and which need a free
Copernicus Marine account.

Ticket #39, acceptance criterion 3. #36 flagged this as the thing it could not settle from
documentation, and it is the hazard that can silently invalidate the recalibration: the
shipped thresholds were fitted on Open-Meteo's `swell_wave_*`, and the reanalysis publishes a
**partitioned** spectrum — a primary swell train (`*_SW1`) and a secondary one (`*_SW2`) —
with nothing stating which of those Open-Meteo serves.

**Short answer: Open-Meteo's Swell behaves like the whole swell field, not the primary train
— but only the size regime this project cares about says so clearly. And separately, both
reanalyses read the swell period roughly half a second to a second high, which matters more
than the partition question does.**

## Method

35,064 hours where the operational feed and the IBI reanalysis both reported, 2022-01-01 to
2025-12-31, joined on the Nazaré local stamp. 11,688 for WAVERYS, which is 3-hourly.

Two things make the comparison readable rather than merely numeric.

**A control.** The two sources read different grid points — Open-Meteo's MFWAM node is ~2 km
from the Proxy Target, IBI's is 1.12 km — and one is an operational forecast while the other
is a reanalysis. So no candidate should match exactly, and "close" has to mean something.
Both sources publish the **Combined Sea** unambiguously, so the gap on *that* variable is the
grid and the model run and nothing else. It is **0.096 m MAE** over all hours and **0.191 m**
on big swell. That is the floor. A Swell candidate landing near it is as good as this
comparison can show; one landing four times above it is measuring something else.

**A discriminating subset.** When the second train is absent — and `VHM0_SW2` reaches exactly
0.00 in this record — both hypotheses predict the same number, and the hour cannot tell them
apart however well it fits. Averaged over everything, those hours dominate and every
candidate scores about the same. The subset where `VHM0_SW2 >= 0.5 * VHM0_SW1` is where the
question is actually asked.

## Finding 1 — the height is the combined field, and the evidence is a size effect

Stratifying the discriminating hours by size resolves what first looks like a contradiction.
Over all discriminating hours SW1-alone appears to win; over the big ones it loses badly.

| Operational swell height | n | SW1-alone bias | combined bias | SW1 MAE | combined MAE | control MAE |
|---|---|---|---|---|---|---|
| 0–1 m | 3395 | +0.003 | +0.172 | 0.088 | 0.187 | 0.056 |
| 1–2 m | 3722 | −0.072 | +0.233 | 0.151 | 0.262 | 0.085 |
| 2–3 m | 967 | −0.282 | +0.205 | 0.334 | 0.295 | 0.130 |
| 3–4 m | 174 | **−0.618** | +0.109 | 0.635 | 0.262 | 0.154 |
| 4–5 m | 43 | **−0.965** | −0.153 | 0.965 | 0.217 | 0.245 |
| 5 m+ | 6 | **−1.053** | −0.207 | 1.053 | 0.224 | 0.262 |

SW1-alone degrades monotonically with size, reaching a **1 m under-read**. The combined
`sqrt(VHM0_SW1² + VHM0_SW2²)` stays flat and, above 3 m, sits within about 0.1 m of the
control floor. The crossover is around 2–3 m; everything this project calls a Gold Day is far
above it.

Direction corroborates it independently and for free: on the 223 hours that are both
discriminating and big, the energy-weighted bearing tracks Open-Meteo at **4.4° MAE** against
**11.1°** for `VMDR_SW1`. Combining two trains from different bearings gives a direction
unlike either, so this is not a restatement of the height result.

**Why SW1 wins below 2 m is not established here.** The likeliest reading is that the two
models draw the swell/wind-sea boundary differently, and that the disagreement is
proportionally largest when the sea is small and mixed — but that is an inference from the
shape of the table, not something measured. It does not affect the conclusion, because the
regime it describes is one where nothing gets called.

## Finding 2 — the reanalysis period reads high, and this is the bigger problem

This was not the question the ticket asked, and it matters more than the answer to the
question it did ask.

| | IBI bias | WAVERYS bias | IBI slope |
|---|---|---|---|
| all hours | +0.483 s | +0.869 s | 0.774 |
| operational swell 2–3 m | +0.565 s | — | 0.828 |
| operational swell 3–4 m | +0.506 s | — | 0.845 |
| operational swell 4 m+ | +0.482 s | +0.886 s | 0.880 |

Both reanalyses report a swell period consistently **above** what Open-Meteo reports for the
same hour, by roughly half a second (IBI) to a second (WAVERYS). The regression slope of
~0.85 says this is not a clean constant offset either — the reanalysis range is compressed
relative to the operational one, so a single additive correction would not undo it. The
energy-weighted period has a slope nearer 1 (0.89–0.95) and fits marginally better at size,
which is consistent with finding 1.

What it costs, stated the way it will actually bite:

| Series | Hours at or above the shipped 13.0 s Go Call bar |
|---|---|
| Open-Meteo `swell_wave_period` (what the bar was fitted on) | 576 |
| reanalysis `VTM01_SW1` | 1311 — **+128%** |
| reanalysis energy-weighted period | 922 — **+60%** |

**Carrying the shipped 13.0 s bar onto the reanalysis unchanged would make it fire well over
twice as often.** Refitting on the reanalysis absorbs this. Feeding reanalysis numbers into
the current bars does not, and the result would look like the model suddenly crying wolf.

## Finding 3 — WAVERYS corroborates the period, not the partition

Two independent reanalyses were fetched precisely so this could be asked, and the honest
answer is that they agree on one finding and not clearly on the other.

- **On the period, WAVERYS confirms IBI and then some** — same direction, larger magnitude
  (+0.87 to +1.16 s). The finding does not rest on one product.
- **On the partition, WAVERYS is equivocal.** Its discriminating-and-big subset holds only 43
  hours (it is 3-hourly and coarser), and there SW1-alone scores 0.434 MAE against the
  combined 0.407 — a difference far too small to carry a verdict, with biases of −0.345 and
  +0.325 that straddle zero rather than settling it.

So **finding 1 rests on IBI**. That is the primary series by design — 1/36° against 1/5°,
1.12 km against 4.53 km, hourly against 3-hourly — and its own evidence is strong and
monotonic across six size bands rather than resting on a single subset. But it is one
product, and this note does not claim two.

## What this does not settle

1. **Whether `VTM01_SW1` and `swell_wave_period` are the same *kind* of quantity.** The
   measured offset is consistent with a mean-versus-something-else distinction, but a bias
   and a slope cannot distinguish "different spectral moment" from "different model". #36
   established that MFWAM publishes no per-partition peak period, so there is nothing to test
   the peak hypothesis against directly.
2. **Whether the mapping is stable across the record.** Everything here is measured on
   2022–2025, because that is the only span where both series exist. The SAR spectra that
   constrain the swell partitions start in March 2016, and 7 of the 29 newly available Gold
   Days fall before that. The relationship measured on the overlap is *assumed* to hold
   earlier, and that assumption cannot be checked with the data this project has.
3. **The 0/360 and summer-time edges**, which are handled but not separately validated: the
   autumn fold renders two UTC hours as one local stamp once a year, and the operational side
   keeps only one of them. One hour a year, inherited from `hindcast.py` rather than
   introduced here.

## Files

| File | What it is |
|---|---|
| `measure.py` | Joins the operational feed to each reanalysis and scores both candidate mappings on four subsets, against a Combined Sea control. `--check` self-tests the circular and energy-weighted arithmetic. |
| `output/mapping_fits.csv` | Every candidate on every subset for both products. |
