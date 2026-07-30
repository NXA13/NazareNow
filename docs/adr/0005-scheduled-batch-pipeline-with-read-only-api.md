# Precompute predictions on a schedule; the API and frontend only read

Third-party wave models publish every six hours, so a prediction for a given date changes at
most four times a day. ADR 0004 makes each prediction expensive — hundreds of Amplification
Model evaluations to build a Predictive Distribution. Computing that per web request would burn
significant compute repeatedly producing an identical answer, and would put a third-party API
inside our request path, making their outage our outage.

Instead a scheduled pipeline runs on the forecast cycle: it fetches Offshore Conditions and buoy
observations, runs the model, derives Watch and Go Calls, and writes the results to a database.
The API and the React frontend are strictly readers of that store.

## Consequences

Pages load without touching a model or a third-party service, and the site stays up and honest —
showing stale results with a timestamp — when Open-Meteo is unreachable.

Every prediction the system has ever made is retained by construction. That gives us the record
needed to evaluate Go Call precision after the fact, which would be lost in a compute-on-request
design.

Notifications become another reader of the same store rather than a special path.

The cost is the largest number of moving parts of the options considered: a scheduler, a
pipeline, a database, an API and a frontend, in two languages.

## Implementation status

As of ticket #7 the pipeline runs **every three hours**, not on the six-hourly cycle the
opening paragraph assumes.

That paragraph is right about wave models in general and wrong about this system. ECMWF WAM
and NCEP GFS Wave do publish every six hours, but the Pipeline Run sends no `models`
parameter, and Open-Meteo's `best_match` at Praia do Norte is identical hour for hour to
MeteoFrance's wave model — which publishes **twice a day**. Three-hourly polling therefore
keeps what the site shows within three hours of a published run, where six-hourly could sit
half an update behind. Sixteen API calls a day against a free-tier limit of ten thousand.

It buys freshness, not accuracy: the forecast is no better, it is simply not needlessly
old. Evidence and a reproducible script in `analysis/forecast_models/`.

The update frequencies themselves are Open-Meteo's documented figures and are **not
independently verified** — the same documentation page gives model identifiers the API
rejects. Confirming them means observing when values actually change across a full day,
which the scheduler's own logs will now show.

"Showing stale results with a timestamp" turned out to be too weak a promise. A timestamp
alone reads as current to anyone not doing arithmetic, so the API states outright whether
results are too old to act on — after two whole cycles without a successful run — and the
interface leads with that rather than leaving it in the footer.
