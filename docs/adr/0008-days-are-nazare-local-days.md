# A day is a Nazaré local day, and a short forecast is refused rather than stored

Two decisions about what a Pipeline Run is allowed to conclude from a provider response.
They are recorded together because they were taken together, and because both are about the
same thing: a run that looks successful while quietly recording something wrong.

## A day is a Nazaré local day

The system groups forecast hours into days, issues one call per day, and computes Lead Time
from the earliest of them. Until now those were **UTC** days, because the Pipeline Run asked
Open-Meteo for UTC and `days.py` sliced the date off the front of each timestamp.

Europe/Lisbon is UTC only in winter. Under summer time the hour stamped `23:00` UTC is
already midnight in Nazaré, so a UTC-grouped day carries an hour belonging to the next local
day — and the call issued for that date was decided partly on conditions from a different
one.

**The domain's day is the local day.** A traveller books a day in Portugal and stands on a
beach in Portugal; ADR 0002's Proxy Target is an instrument in Portuguese water. Nothing in
this system has any use for a UTC day, and CONTEXT.md exists to stop exactly this sort of
quiet mismatch between a word and what it denotes.

The Pipeline Run therefore requests `timezone=Europe/Lisbon` **and verifies the response
came back on it**, the same way it already pins and verifies units: a request is a
preference, and only the response is evidence. A provider-side default that ignored the
parameter would move every day boundary by an hour while every number on the page still
looked plausible.

### Why now rather than later

The affected window is about 28 days of every Big-Wave Season — and 25 of them are the first
three weeks of October, before summer time ends:

| Season boundary | Days at UTC+1 |
|---|---|
| 1–25 October | 25 |
| 29–31 March | 3 |

Ticket #28 exists to have the scheduler running *before October*, so that the system
collects a full season of its own calls. Those October days are both the start of the record
and the affected window.

The change costs nothing today, because no deployed store has accumulated anything. After
#28 it is permanent: the record ticket #11 scores would be grouped one way for its first
weeks and another way afterwards, and no later analysis could separate the two. **This is a
decision whose price rises on a fixed date and never falls.**

### What this does not change

Hours are still shown as the provider sent them, now labelled "Nazaré" instead of "UTC".
Nothing converts a timestamp into the viewer's own zone: a reader in Sydney planning a trip
to Portugal wants Portuguese hours, and rendering 06:00 as their own afternoon would be
actively misleading about when to be on the beach.

`fetched_at` remains UTC with an offset — it is a fact about our clock, not about Nazaré,
and staleness arithmetic depends on it being unambiguous.

## A short forecast is refused rather than stored

`MINIMUM_FORECAST_HOURS` was an absolute floor of **24** against a healthy run of about
**216**. A degraded response carrying 30 hours therefore passed, replaced nine days of
forecast with a fragment, and reported success — the failure the constant's own comment
described at the previous threshold, moved rather than removed (#25).

Two guards now, because neither is sufficient alone:

- an **absolute floor** of 120 hours, which catches a response that is short in isolation —
  including the first run into an empty store, where there is nothing to compare against;
- a **relative guard**: no run may replace a stored forecast with less than half of it. 150
  hours is a respectable forecast unless 300 are already stored, and no provider will hand
  those back once they are gone.

### The fraction is deliberately coarse

Nobody yet knows what a legitimate short forecast from this provider looks like. Marine
coverage genuinely varies, and a rule that refused every shrinkage would turn an ordinary
provider change into an outage needing a code edit to clear.

Choosing a precise threshold today would be false precision. Choosing a permissive one would
reintroduce the bug. So the guard is coarse **and** the refusal is now evidence: since #30, a
refused run is a durable record carrying its failure kind and the payload that caused it. A
provider genuinely shortening its horizon shows up as a run of identical
`payload_unrecognised` failures with the responses attached — which is what this number
should eventually be set from, rather than from a guess made before seeing any.

### Consequences

Test fixtures had to grow. Several carried one to three days of hourly data, which is now a
degraded response by definition, and would have exercised the rejection path in every test
rather than the behaviour each was written for. The interesting days keep their shape and
the added days are uniform filler.

## Considered and rejected

**Keep UTC and document it.** Coherent, and cheaper today. Rejected because it makes the
system's central noun mean something no user means by it, and every future reader of
`days.py`, the API and the interface has to hold the discrepancy in their head. The
documentation would be correct and the model would still be wrong.

**Convert in the interface instead.** Puts a domain rule in the presentation layer, which
ADR 0005 forbids, and leaves the *stored* record — the thing #11 scores — grouped by a
boundary nobody intended.

**Raise the absolute floor alone.** Simplest, and still absolute: it would fail the same way
again the first time the healthy range grew, which is the shape of the bug rather than its
size.
