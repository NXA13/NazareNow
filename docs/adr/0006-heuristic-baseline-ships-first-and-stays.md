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
