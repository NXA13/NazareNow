# Ship the Heuristic Baseline first, and keep it forever

The surf community's rule of thumb — Significant Wave Height above 3m, period above 14s,
direction from W-NW, wind light and offshore — is a complete predictor requiring no machine
learning at all. We implement it as the first Amplification Model, which lets the entire system
be built, deployed and demonstrated end to end before any model is trained.

More importantly, we keep it permanently. A learned model reported in isolation is
uninterpretable: 0.87 AUC means nothing without knowing what guessing well would have scored.
The Heuristic Baseline is the number the learned model has to beat, and the honest possibility
that it does not is itself a finding worth reporting.

## Consequences

The Amplification Model must be swappable behind a stable interface from the first commit, since
we intend to replace its implementation while keeping everything downstream unchanged.

Every evaluation of the system reports the learned model and the Heuristic Baseline side by
side. Neither is reported alone.

The first deployable slice contains no machine learning, which must not be mistaken for the
project being off-track — it is the point.

## Amendment: the thresholds were fitted (ticket #12)

The numbers quoted above — 3 m, 14 s — are the community's rule of thumb as this decision
found it, and are kept here as the record of where the baseline started. They are no longer
what ships. Ticket #12 fitted them to the Gold Days: 3.75 m, and a swell period bar of 12.5 s
for a Watch against 13 s for a Go Call. They now live in `backend/src/nazarenow/thresholds.json`
rather than in code, and `analysis/calibration/` is the fit.

Nothing in the decision changes. The Heuristic Baseline is still the permanent benchmark, and
a calibrated rule of thumb is a *harder* floor for a learned model to clear than an unfitted
one — on the operational panel it went from catching 3 of 9 Gold Days to 7 of 9 at Go Call.
Ticket #13 has more to beat than this ADR anticipated, which is the outcome to want.

The requirement that both be reported side by side is unaffected, and now carries a second
obligation: the calibration rests on nine Gold Days, and any figure derived from it states
that alongside the figure.
