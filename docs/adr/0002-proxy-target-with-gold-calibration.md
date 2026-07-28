---
status: accepted, revised after the coverage analysis in #2
---

# Train on Monican02's Significant Wave Height, calibrate on hand-verified Gold Days

The quantity we care about is Face Height at Praia do Norte, and it has no
machine-readable history — it is estimated by expert panels from video, months after the
fact. We cannot train on it. The Instituto Hidrográfico operates two moorings off Nazaré,
and we adopt the inshore one, **Monican02**, as the Proxy Target: it sits roughly 15 km
out near the canyon head, so its readings carry the local Amplification we are trying to
learn. Its record runs hourly from 2010 and is free from the Copernicus Marine In Situ
TAC.

We accept explicitly that the Proxy Target is not the thing we care about. To bridge the
gap we hand-assemble a small set of Gold Days — contest days, ratified records,
documented sessions — and use them solely to calibrate what predicted Significant Wave
Height corresponds to a genuinely giant day. Train on the abundant proxy, threshold on
the scarce truth.

**Monican01**, the second mooring, is retained as an *input* and never as a target. It
lies ~55 km offshore in deep water, where it measures approximately the open-ocean swell
that forecast providers already supply — so predicting it would largely mean predicting
our own inputs. As a feature it is valuable: a measured offshore reading rather than a
modelled one.

The two must never be spliced into a single target series. They sit 40 km apart in
materially different water, so a combined series would mean one thing on some days and
something else on others. That is an inconsistent target, and no quantity of data
repairs one.

## Considered Options

Classifying XXL Days directly was rejected: roughly 100-300 positives against 5,500
winter days, with labels that are subjective and where absence of news coverage does not
imply small surf.

Estimating Face Height from webcam imagery by computer vision measures the real quantity
and is the strongest option technically, but no historical imagery archive exists, so
data collection could only start going forward — first usable season would be winter
2026/27. Revisit later as an extension, not as the foundation.

## Consequences

Every claim the system makes about Face Height rests on a calibration built from fewer
than a hundred days. That uncertainty must be surfaced to the user, not hidden behind a
confident number.

**Fourteen usable Big-Wave Seasons, not sixteen.** Monican02 recorded nothing at all in
2013/14 and 2016/17, and five further seasons fall between 16% and 37% coverage.
Evaluation splits must be made on what was actually recorded; describing this as sixteen
years of data would mislead. Monican01 covers 632 Usable Days that Monican02 missed, and
2013/14 is the only season both lost — so as an input it also partially fills the gaps.

**Significant Wave Height is a weak predictor of Face Height**, now measured rather than
suspected. Across the record days checked in #2, two world-record days sat near 5.3 m
while a swell 50% larger produced no comparable wave. The Decision Model should therefore
emit a probability of a giant day rather than a predicted height, and the Gold Day
calibration should expect a noisy threshold.

**An undetected instrument change cannot be ruled out.** The source files carry no sensor
model, serial number or deployment record, so a swapped instrument across the record
would be invisible. Position is recorded only to 0.01° (~1.1 km), which establishes that
neither mooring was relocated substantially, not that neither moved.

## Revision history

Originally written during design, before any data had been retrieved. It described a
single buoy "in 90m of water near the canyon" recording "hourly since 2009", downloadable
"via EMODnet ERDDAP". The coverage analysis in #2 found that no such instrument exists —
the record reaching back to 2009 belongs to the deep-water mooring, not the inshore one —
that EMODnet's download URLs all return 404, and that coverage is far less even than
assumed. The strategy survived; the facts did not. See `analysis/buoy_coverage/` and #17.
