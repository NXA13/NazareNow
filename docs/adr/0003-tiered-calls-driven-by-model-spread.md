# Tiered Watch/Go/Confirmed calls, with uncertainty taken from Model Spread

ADR 0001 requires the Amplification Model to emit uncertainty, but the marine forecast APIs
available to us offer no ensemble product — there is no spread to read off. Instead we query
several independent wave models for the same target date (ECMWF WAM, MeteoFrance MFWAM, DWD
EWAM, NCEP GFS Wave) and treat their disagreement as the uncertainty estimate. Free, requires
no extra infrastructure, and reflects genuine forecast doubt rather than a model's opinion of
its own confidence.

That uncertainty then drives a tiered alerting policy borrowed from national weather services:
a Watch at long range optimised for recall, escalating to a Go Call at medium range optimised
for precision, with a Confirmed statement at short range for users already in transit. A single
threshold on predicted height would have forced one operating point on two audiences with
opposite tolerances for being wrong.

## Considered Options

A decision-theoretic policy — booking when expected value peaks, given flight prices rising as
the date approaches — is the more rigorous formulation and remains the natural extension. It
was rejected for now because it requires sourcing historical flight prices, an entirely separate
data-acquisition problem, and because it needs an invented figure for the value of witnessing
the phenomenon.

## Consequences

The data pipeline must fetch and store multiple wave models per date, not one. This multiplies
API calls and storage, and means a model being unavailable degrades the uncertainty estimate
rather than the prediction.

Watch and Go Call must be evaluated against different metrics. Reporting a single accuracy
figure for the system would be meaningless.

## Implementation status

As of ticket #6 the tiers are decided by Lead Time alone. Model Spread does not exist
yet — ticket #8 introduces it — so nothing in the system measures forecast agreement, and
no part of it may claim a forecast has "converged". A Watch is kept genuinely looser than
a Go Call in the meantime by dropping the wind condition, which carries little information
at range; without that the two tiers were one rule with two names, which is what this ADR
exists to prevent.
