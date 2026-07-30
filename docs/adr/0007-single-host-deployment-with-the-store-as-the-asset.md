# Deploy to one small host with persistent disk, and treat the store as the asset worth protecting

ADR 0005 keeps every result in a SQLite file that a Pipeline Run writes and the API reads.
That decision, made for operational simplicity, sets the binding constraint on where this
can run: **the process needs a disk that survives restarts, and the writer and reader need
to see the same one.** Platforms whose filesystems are ephemeral or per-instance —
serverless functions, most PaaS free tiers, CI runners on a cron — cannot host this without
first replacing the store, which would mean reopening ADR 0005 to solve a hosting problem
rather than a data one.

So: a single small always-on host with a persistent volume, running three things — the
scheduler, the API, and a reverse proxy serving the built frontend and terminating TLS.
Cheap, boring, and the same shape locally as in production, which means a fault can be
reproduced on a laptop.

## What is actually being protected

The instinct is to treat a deployment as a way to show the site to people. Here the more
important consequence is that **the store starts accumulating something irreplaceable**.

ADR 0005 promises "every prediction the system has ever made is retained by construction",
and ticket #11 scores Go Call precision from that record. The Gold Days in
`analysis/gold_days/` can only ever measure **recall** — they say which days were giant,
and silence about a day is not evidence it was flat, so no honest precision figure can come
from them. The only unbiased source of negatives is this system running forward and
recording what it called on every ordinary day nobody wrote about.

That record cannot be backfilled. A forecast archive can be re-fetched; a record of what
*this system predicted, at what Lead Time, on a day it turned out to be wrong about* exists
only if we were running and kept it. Losing the disk loses the evidence for every accuracy
claim the project will ever make.

Backups are therefore not operational hygiene here. They are the reason the deployment
matters, and they must be off the host and restorable — an untested backup is a belief, not
a backup.

## Consequences

**Timing has value that waiting destroys.** Nazaré's Big-Wave Season runs October to March.
A deployment running before October collects a full season of forward record; one that
slips past it collects none, and #11's precision figure waits a year. This is the only
piece of work in the project with a deadline set by the ocean rather than by us.

**The site will be publicly reachable while its thresholds are uncalibrated.** The interface
already says so — it states that the calls come from a rule of thumb rather than values
fitted to Gold Days, that the predicted height is the offshore figure carried through
unchanged, and that no buoy reading reaches the page. Deploying does not change what the
system knows; it changes how many people can act on it. That is a reason to keep the
disclosures prominent, not a reason to wait, because waiting also costs a season.

**Open-Meteo's free tier is non-commercial.** A freely accessible site is within it. If this
ever carries advertising, subscriptions or referral revenue, the licence has to change with
it, and that is a decision to make deliberately rather than discover.

**One host is a single point of failure, and that is accepted.** The site going down for an
afternoon costs nothing; the *store* being lost costs the project its evidence. Effort goes
into backup and restore rather than into uptime.

## Considered options

**A managed platform with a database add-on** removes the host but replaces SQLite, which
means reopening ADR 0005's storage decision to solve a deployment problem. If the store
later outgrows a file — concurrent writers, or a dataset that stops fitting comfortably —
that is the moment to revisit it, on its own merits.

**Static hosting plus scheduled CI runs** was rejected for the same reason: the runner is
wiped after every job, so the accumulating record would have to live somewhere else anyway,
and committing a database to the repository to work around that would make every run a
commit.
