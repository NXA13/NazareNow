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

**#8 settled this, and the requirement above is met by measurement rather than by alignment.**
Run age still cannot be read from the provider and the runs are still not aligned. What #8
established (`analysis/model_spread/alignment.py`, finding 4) is how much that costs: staleness
accounts for roughly **6% of the measured spread at one day** on the expected cadence gap,
rising to **29% at six days** in the worst case, over 6,192 archived hours. The figure is real
and it grows with Lead Time, so the concern above was well founded.

It does not block the mechanism, because the contamination has a direction. Sampling two
providers at different run ages can only make them look *more* different than they are; it
cannot hide genuine agreement. So staleness inflates Model Spread, a wide spread reads as
doubt, and doubt makes the system quieter — **the error is always toward caution, never toward
a Go Call that should not have been issued.** Model Spread is therefore an upper bound on
disagreement, loose at long range, and must not be quoted as a calibrated uncertainty.

Two limits on that finding. It is measured on **Combined Sea**, because the archive carries no
Swell partition per model, while Model Spread is defined on Swell — the leap is argued, not
measured, and `alignment.py` reports both partitions' live spread so its size is visible. And
the 6-to-12-hour figures are extrapolated from a 24-hour measurement by a fitted growth
exponent of 0.83; the exponent is measured across six intervals rather than assumed, but the
extrapolation still runs below the measured range.

**Model Spread now drives the Go Call tier, which is the mechanism this ADR opens with.** #8
shipped in two parts. The first was the whole measurement and none of its consequence: five
wave models fetched in one request, stored per model per forecast hour rather than averaged on
arrival, differenced per date, and displayed. The second reaches `decide`.

**The rule is agreement about the decision, not a threshold on the width.** A Go Call requires
the *lowest organisation's* swell period at the deciding hour to still clear the calibrated Go
Call bar. Two models a second apart and both well above the bar do not disagree about anything
a traveller would act on; two models straddling it disagree about the only thing being asked.
A day the models divide over falls to a Watch — the swell is still worth watching, it is
simply not yet worth a flight.

The obvious alternative, a bar on the spread itself in seconds, was rejected because **nothing
in the record can supply that number**. Per-model Swell readings have been collected by this
system only since #8's first half, `analysis/model_spread/` measured its one live sample on a
0.4 m summer sea and says in terms that it must not be believed, and a threshold chosen anyway
would be a guess wearing a calibration's clothes. The rule as shipped introduces no new
constant: it reuses the bar #12 and #43 fitted to the Gold Days.

**What it costs was measured, because this ADR's own tier rule is what changed.** Not by the
backtest — a Hindcast is what the ocean did, holds no forecast and therefore no disagreement,
so it reproduces identical tables either side of this and states that assumption in its own
source. `analysis/model_spread/agreement.py` measures the gate directly on 18,264 archived
hours from 2024-07 to 2026-07, the span where all three organisations carry a real Swell
partition: **the gate withholds 4 of 25 Go Call days, 16%**, all four in one season, and
**neither of the two Gold Days in the span loses its Go Call**. That figure is a lower bound,
because archived per-model readings are near-analyses while a Go Call is issued two to seven
days out, where the same measurement shows spread growing.

**A Confirmed statement is deliberately not gated.** It is issued a day out to somebody already
travelling and recommends no booking, so there is no flight for disagreement to protect; and
because a Watch requires a Lead Time beyond the Confirmed band, gating it would drop those days
to silence rather than to a weaker call.

Two properties of the measurement bear on how the gate reads it. A date's *displayed* spread is
taken from its **median hour** — a real hour's real disagreement, chosen so that half the day's
hours disagree more and half less — while this ADR judges a day on its best *matching* hour.
Those are different hours, and the gate uses the second: every hour is decided carrying its own
ensemble verdict, so whichever hour wins the day brings the right spread with it, computed from
the per-hour store without refetching or a migration. The call records which it was, because
that cannot be recovered from the median the record displays beside it. And swell direction is
differenced as a **compass arc**, not a subtraction; two models agreeing on a north swell at
355° and 5° are 10° apart, and the plain range calls them 350° apart, which would put maximum
doubt on a day of near-perfect agreement in the direction the canyon focuses best.

**Direction and height are measured and do not gate anything**, which is a choice rather than
an omission. Period is the condition #11 found decides tiers, it is the one the Go Call bar is
written in, and the direction spread this project has observed was 60.5° against a 75° arc on a
0.4 m sea — a figure the same README refuses to generalise from. Adding a second gated variable
on that evidence would spend a cost nobody has measured. The Big-Wave Season is what settles it.

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
