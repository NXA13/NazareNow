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
