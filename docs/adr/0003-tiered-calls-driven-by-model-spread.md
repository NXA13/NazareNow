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

**Only one of the two tiers was given a price here, and ADR 0010 gives the other one.** This
ADR states what a Go Call may cost — a budget per Big-Wave Season — and says only that a Watch
is "optimised for recall", which the calibration read as a constraint with no ceiling. On six
Gold Days that was invisible; on twenty-five it put a Watch on more than a third of the season
for recall that did not survive the held-out split. ADR 0010 gives the recall tier a budget of
its own, and the two tiers are now chosen by the same rule with different numbers. The sentence
above still stands: they are still evaluated against different metrics, and the Watch tier is
still the looser of the two.

## Implementation status

**The roster named above cannot be implemented as written.** Requested on its own at Praia
do Norte, `ecmwf_wam` returns `swell_wave_height: null` — it carries a combined `wave_height`
and no swell partition, and `ecmwf_wam025` behaves the same way. The Amplification Model
consumes swell, so ECMWF WAM is unusable here whatever the quality of its wave model. Three
of the four models this ADR names do work. Ticket #8 revises the roster rather than
implementing it; the per-model evidence table is in `analysis/forecast_models/`.

Three further corrections from the same investigation bear on #8. The documented identifiers
`gfs_wave025` and `gfs_wave016` are rejected by the API — the working forms are
`ncep_gfswave025` and `ncep_gfswave016`. `gfs_seamless`, `gfs_global` and
`meteofrance_seamless` all return 200 with null values here, so an implementation trusting a
success response would record a model as agreeing when it had said nothing at all. And EWAM
and GWAM are both DWD: counting them as two independent opinions overstates the ensemble
this ADR's uncertainty estimate rests on.

One consequence is sharp enough to belong here rather than in the ticket. The working models
do not publish on the same cycle — MeteoFrance and DWD twelve-hourly, NCEP six-hourly — so at
many moments one model's forecast is up to six hours older than another's. Differencing them
naively measures our sampling of their publication schedules alongside genuine disagreement
and reports the sum as uncertainty. #8 must align model runs before differencing, or this
ADR's central mechanism will be reading staleness as doubt.

As of ticket #6 the tiers are decided by Lead Time alone. Model Spread does not exist
yet — ticket #8 introduces it — so nothing in the system measures forecast agreement, and
no part of it may claim a forecast has "converged". A Watch is kept genuinely looser than
a Go Call in the meantime by dropping the wind condition, which carries little information
at range; without that the two tiers were one rule with two names, which is what this ADR
exists to prevent.

Which conditions gate which tier is decided on **condition identity**, and every tier names
the conditions it requires. Neither half of that is incidental. An early implementation
substring-matched the Heuristic Baseline's own English failure messages, so rewording a
message moved days between tiers and any other implementation of the interface — the swap
ADR 0006 exists to allow — had every day it judged fall into Watch. The fix for that named
the Watch tier's conditions and left a Go Call asking only whether every condition a model
*chose to judge* held, which let a model that never judges wind issue a Go Call through an
onshore gale. Both are the same failure: a tier deciding on something other than the
conditions it is defined by.

A day is judged on its best *matching* hour rather than its largest, so a clean morning
window under an onshore afternoon peak is not discarded. That protects the recall a Watch
is optimised for, but it cuts against the precision a Go Call is optimised for: a single
clean hour in twenty-four can currently earn one. No minimum window is imposed here
because ticket #12 calibrates thresholds against the Gold Days and should own that number.

**#12 owned it and declined to set one.** Fitting a minimum-window parameter needs Gold Days
to fit it against, and only nine carry real Swell measurements — six of them in the fitting
split. That is not enough to distinguish "three clean hours" from "six" from "one", and a
number chosen anyway would be a guess wearing a calibration's clothes, which is the failure
this project keeps having to undo. It stays open, and #36 is the ticket that could widen the
record enough to answer it.

Meanwhile every call states how many of the day's hours matched, so a call resting on
one hour says so in the reasons the user reads. That count is taken against the conditions
the call itself rests on — a Watch ignores wind by design, so counting every condition made
a genuine Watch day report "0 of 24 forecast hours match every condition" beside its own
badge: true arithmetic, and nonsense as an explanation of that call.
