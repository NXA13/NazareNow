# Train on buoy Significant Wave Height, calibrate on hand-verified Gold Days

The quantity we care about is Face Height at Praia do Norte, and it has no machine-readable
history — it is estimated by expert panels from video, months after the fact. We cannot train
on it. The Instituto Hidrográfico's MONICAN buoy, in 90m of water near the canyon, has
recorded Significant Wave Height hourly since 2009 and is freely downloadable via EMODnet
ERDDAP. We adopt that as the Proxy Target.

We accept explicitly that the Proxy Target is not the thing we care about. To bridge the gap we
hand-assemble a small set of Gold Days — contest days, ratified records, documented sessions —
and use them solely to calibrate what predicted Hs corresponds to a genuinely giant day. Train
on the abundant proxy, threshold on the scarce truth.

## Considered Options

Classifying XXL Days directly was rejected: roughly 100-300 positives against 5,500 winter days,
with labels that are subjective and where absence of news coverage does not imply small surf.

Estimating Face Height from webcam imagery by computer vision measures the real quantity and is
the strongest option technically, but no historical frame archive exists, so data collection
could only start going forward — first usable season would be winter 2026/27. Revisit later as
an extension, not as the foundation.

## Consequences

Every claim the system makes about Face Height rests on a calibration built from fewer than a
hundred days. That uncertainty must be surfaced to the user, not hidden behind a confident
number.
