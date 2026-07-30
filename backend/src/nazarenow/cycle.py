"""The forecast cycle: how often results are refreshed, and when they stop being current.

Both numbers are domain policy rather than mechanism — they describe how fresh this
project considers its data to be, which the scheduler acts on, the API reports and the
interface tells the user. They live here, apart from all three, so that the read-only API
does not have to import the writer to learn them.

That mattered: reading the threshold from `schedule` gave `api` the import graph
`api → schedule → pipeline → sources.open_meteo`, so the module whose own header says
"nothing here should ever grow a network call outward" transitively imported the module
that makes them. Nothing broke, and the layering ADR 0005 exists to protect was gone.
"""

from __future__ import annotations

# Three hours, in seconds — the interval between Pipeline Runs.
#
# On evidence rather than assumption. ADR 0005 set the cadence from "third-party wave
# models publish every six hours", which is true of ECMWF WAM and NCEP GFS Wave and not of
# the model this system actually receives: the Pipeline Run sends no `models` parameter,
# and Open-Meteo's `best_match` at Praia do Norte is identical hour for hour to
# MeteoFrance's wave model, which publishes twice a day.
#
# Three-hourly therefore keeps what the site shows within three hours of a published run,
# where six-hourly can sit half an update behind. Two API calls per run makes it sixteen a
# day against a free-tier limit of ten thousand. It buys freshness, not accuracy: the
# forecast is no better, it is simply not needlessly old. See `analysis/forecast_models/`.
INTERVAL_SECONDS = 3 * 60 * 60

# When results stop being presentable as current: two whole cycles without a successful
# run. One missed run is a blip — a provider hiccup, a restart — and calling that stale
# would train users to ignore the warning. Two means something is actually wrong.
STALE_AFTER_SECONDS = 2 * INTERVAL_SECONDS

# The same figure in the unit a person reads, so the sentence shown to a user is derived
# from the threshold rather than retyped beside it. The interface said "at least six hours"
# as a literal while a docstring claimed the number was single-sourced; changing the
# cadence would have left the page asserting a duration that was no longer true, and no
# test would have noticed.
STALE_AFTER_HOURS = STALE_AFTER_SECONDS // 3600
