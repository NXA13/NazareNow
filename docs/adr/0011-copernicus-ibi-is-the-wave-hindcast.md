# Copernicus IBI is the wave Hindcast, and ERA5 supplies only wind

ADR 0004 decided that the Amplification Model learns from a Hindcast rather than from archived
forecasts, and named **ERA5** as the Hindcast in passing. That name is no longer true. #36
established that Copernicus publishes a genuine Swell partition back to 1980, #39 ingested
`IBI_MULTIYEAR_WAV_005_006` / `cmems_mod_ibi_wav_my_0.027deg_PT1H-i` and refit the calibration
against it, and every wave threshold the project ships was fitted against IBI — then translated
into the operational units a Pipeline Run reads, which is why `thresholds.json` carries numbers
in Open-Meteo units and the translation constants beside them. ERA5 stays, but only for wind.

We record that split here. It was made in code and in measurement without ever being written
down as a decision, and ADR 0004 — the only ADR that names a source at all — still names the
one we left.

## Why this is an ADR and not only an amendment to ADR 0004

ADR 0004's decision is the *separation*: learn the physical relationship from clean inputs,
characterise forecast unreliability independently, and combine them at serving time. Swapping
one Hindcast source for another leaves that entirely intact. By ADR 0009's test — does this
change the shape of the earlier decision, or only its numbers? — the correction to ADR 0004 is
an amendment, and it carries one.

What does not fit inside that amendment is that **choosing IBI was its own decision**. ADR 0004
did not make it; it assumed a source while deciding something else. This one had real
alternatives, a real cost, and a result a reader will not guess: the Hindcast is assembled from
two products rather than one, and a reader who finds ERA5 wind beside IBI waves is entitled to
ask why. Recording that as a footnote to a decision about forecast
error would file the reasoning where nobody looking for it would search. ADR 0009 and ADR 0010
set the precedent of a new record over an edit.

## What forced it

ERA5 was never chosen for waves so much as inherited. It was the only free Hindcast source
reaching back far enough, and it carries the **Combined Sea** only — no Swell partition. The
Heuristic Baseline's conditions are stated in Swell terms, so #11 had to *reconstruct* Swell
from ERA5's Combined Sea, and that reconstruction recovered **41% of threshold crossings** at
the then-shipped 13 s bar. Its nearest node sits **25.7 km WSW** of the Proxy Target, far
enough that #11 flagged distance alone as a contributor to error.

The consequence was the binding constraint on every accuracy claim the project made: the
calibration stood on **9 Gold Days**, because those were the ones the operational feed covered
and the reconstruction could not be trusted to add the rest.

IBI removes all three problems at once. It publishes `VHM0_SW1` / `VTM01_SW1` / `VMDR_SW1` and
the matching secondary train with CF standard names that say what they are, on a 1/36° grid
whose nearest **wet** node — checked against the product's own mask file, not assumed — is
**1.12 km WSW** of the Proxy Target, hourly, from 1980. It covers **38 of 38** Gold Days. The
calibration now fits on 25 and validates on 13.

`analysis/waverys/README.md` is the verification and `analysis/overlap/README.md` is the
measurement.

## What we rejected

**Keeping ERA5 for waves.** A 41%-recall reconstruction standing between the record and every
Swell threshold, at 25.7 km, when a product exists that publishes the partition directly at
1.12 km. The reconstruction was a workaround for the absence of an alternative, and the
alternative turned out to exist.

**WAVERYS as the primary series.** `GLOBAL_MULTIYEAR_WAV_001_032` was the product #36 set out to
verify, and it is adequate — same MFWAM family, same six partition variables, 38 of 38 Gold
Days, same free credentials. IBI beats it on every axis that matters here: 1/36° against 1/5°,
1.12 km against 4.53 km, hourly against 3-hourly. Hourly also matters beyond resolution, because
`hindcast.py` and `backtest.py` count Usable Days from 24 rows and a 3-hourly series would have
forced that denominator to change.

WAVERYS is **kept as the cross-check** rather than dropped, and it earned the place: it
independently confirmed the swell-period offset below, in the same direction and larger. It was
equivocal on the partition question — its discriminating-and-big subset holds 43 hours — so that
finding rests on IBI alone, and `analysis/overlap/README.md` says so rather than claiming two
products.

**Taking wind from Copernicus too.** The IBI wave product carries no wind variables — only wind
*wave* — so a single supplier would mean a third product, another download and another refit,
for an input that
blocks nothing in the record once ADR 0009's light-wind exemption is applied. ERA5 wind is
adequate, already cached, and already validated on arrival. This is the reason ERA5 stays, and
the reason the project reads two products rather than one.

## Consequences

**The thresholds had to be refit, and were.** IBI reads the swell period roughly **+0.5 s** high
against the operational feed, with a regression slope near 0.85 — a compressed range, not a
clean offset. Carrying the shipped 13.0 s Go Call bar onto IBI unchanged would have
fired **128% more often**. #39 refit rather than carried across, which is why the numbers in
`thresholds.json` moved and why figures measured in ERA5-era units are not comparable to figures
measured now.

**ADR 0004's stated bound is inverted.** It says "the buoy record, not ERA5, bounds the training
set", true when ERA5 reached back to 1940. IBI's cached download begins **2011-01-01** while
Monican02 begins 2010-06-12, so the *Hindcast* now bounds the front — 2,215 hours of Proxy
Target have nothing to pair with, and it costs the 2010/11 Big-Wave Season most of its autumn.
At the far end IBI stops 2026-04-21 against the buoy's 2026-06-30, a further 750 hours.

This is a **download range, not a product limit** — IBI reaches 1980, so unlike the ERA5-era
claim it is recoverable with a re-download rather than a fact about the archive.
`reanalysis.START` matches `hindcast.START` because it was set for #11's backtest, which is the
right bound for a backtest and the wrong one for training. Recorded as limitation 5 in
`analysis/training_dataset/README.md`.

**"Roughly 76,000 quality-controlled hourly observations from 2010" is now 73,601 rows from
2011-01-01.** ADR 0004's figure was an ERA5-era estimate. Against IBI it reads as an unexplained
shortfall, when in fact it is the range mismatch above.

**A second train/serve skew, which ADR 0004 does not cover.** ADR 0004 anticipated one — clean
Hindcast in training, noisy forecast at serving — and answers it with a Forecast Error Profile.
Training on a *different product* adds something that profile cannot touch: perturbing a forecast
by its own error distribution does not correct a systematic offset between two models, and with
a slope of ~0.85 no additive correction undoes it either. #13 handled it by keeping the fit in
native reanalysis units and inverting the two translated quantities from operational into
reanalysis units at inference (`Translation.invert`), with the constants riding in the exported
JSON. That is a consequence of this decision, not of ADR 0004's, which is why it is recorded
here.

## What this does not settle

**Whether the IBI-to-operational mapping is stable across the record.** It is measured on
2022–2025, the only span where both series exist, and *assumed* to hold earlier. One documented
reason to doubt it: the SAR spectra that constrain the swell partitions begin March 2016, and 7
of the 29 newly available Gold Days fall before that. It cannot be checked with the data this
project has.

A second reason is suspected rather than documented, and the distinction is the point. WAVERYS's
QUID records its source moving from ECWAM cy38 to cy42 in 2020. **That is WAVERYS's
discontinuity, not IBI's** — #36 read IBI's catalogue entry, product page and mask file but not
its QUID, so whether IBI carries the same break is unknown. The two share the MFWAM family,
which makes it worth suspecting and does not make it a fact.

**Whether wind carries the same skew — settled by #51, and the guess above was wrong.** This
ADR expected the gap to be small, on the reasoning that 10 m wind speed is far less
model-dependent than a partitioned swell period. Measured over three Big-Wave Seasons at the
Proxy Target (`analysis/wind_products/README.md`), the forecast product reads **1.5 km/h**
lighter than ERA5 in the band the exemption decides in, and 2.1 km/h lighter in the window
straddling the bar. Against a bar with 0.2 km/h of margin, that is not small: it is roughly ten
times the margin and four times the 0.5 km/h step the bar is rounded to.

The exemption is therefore translated like the wave bars, and ships at **14.5 km/h** rather
than the fitted 16.5. Untranslated it was admitting hours the fit would have refused at nearly
four times the rate it refused hours the fit would have admitted; translated, the two errors
are balanced. The wind *feature* of the Amplification Model crosses the same boundary and stays
untranslated, because there the same gap moves a prediction by about 0.01 m against an error of
0.356 m — the measured reason, not the old premise.

What the measurement does **not** remove is the scatter. The residual is 3.45 km/h, so even the
correctly placed bar disagrees with the fit's intent on about 13% of hours. Translating fixes
where the bar sits, not how noisy the reading it is applied to is.

**Whether the wave translation is the right shape outside the regime it was fitted in —
measured by #52, and it is not.** The consequence recorded above keeps the fit in native units
and inverts the translation at inference. It says nothing about where that translation is
fitted. It is fitted on hours at or above 3 m, in the regime the *thresholds* operate in, and
then applied by the Amplification Model to every hour served — 84% of which sit below 3 m of
Combined Sea. Measured on the 35,064 hours where both products reported
(`analysis/amplification_model/README.md`, "Is the Translation the right shape?"), the shipped
height transform **over-predicts the operational Combined Sea by 0.22–0.27 m below 2 m**, and
`LearnedAmplification._restate` inverts that error into the model's dominant feature on the
majority of hours a Pipeline Run touches.

Two things follow that this ADR did not anticipate. The first is that the *thresholds* are
unaffected — they are applied at size, inside the fitted range, which is why the bar was set
there. The second is that the Amplification Model and the calibration have different needs from
one transform and currently share it, because `fit_translations()` returns one object to both.
Refitting the height transform where the model uses it would move the shipped Watch and Go Call
bars, and #52 measured that too: the two candidates that fix the height error also drop the Go
Call bar by 0.3 s, on the strength of a swell-period fit that is *worse* in the regime that bar
operates in. Fixing this properly means separating the two consumers, not moving the bar.

Left open rather than decided. #52's brief put reshipping out of scope, and #39's rule applies
to any threshold that moves — it moves by being rewritten by the fit, never by hand.

**Whether the training set should be extended to IBI's real reach.** It could go back to 1980;
it stops at 2011-01-01 for a reason that belonged to a different module. Extending it means a
re-download with Copernicus credentials and would move #11's span underneath it.
