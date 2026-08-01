"""Keep the store current without anyone touching it.

ADR 0005 puts a Pipeline Run on the forecast cycle and makes the API and interface strictly
readers of what it leaves behind. This is that cycle.

**Three-hourly, on evidence rather than assumption.** The Pipeline Run sends no `models`
parameter, so Open-Meteo chooses, and at Praia do Norte that choice is identical hour for
hour to MeteoFrance's wave model — which publishes twice a day. Polling every three hours
keeps what the site shows within three hours of a published run; six-hourly can sit half an
update behind. Two API calls per run makes this sixteen a day against a free-tier limit of
ten thousand. It buys freshness, not accuracy: the forecast is no better, it is simply not
needlessly old. See `analysis/forecast_models/`.

**A failed run must lose the run, never the schedule.** Open-Meteo will be unreachable
sooner or later, and an unattended system that dies on one bad fetch is worse than no
schedule at all: it stops silently, and the site goes on serving old data with nobody
watching. So every exception is caught here — including ones nothing anticipated, because
the whole point is to survive what nobody thought of.

A failed run changes no conditions, forecast or calls. `Store.record_run` is a single
transaction, so the previous ones stay exactly as they were, and the interface marks them
stale rather than presenting them as fresh — but the attempt itself is recorded (ticket
#30), because a gap in the record with no explanation beside it cannot be told apart from
a host nobody had switched on. A run that failed partway also keeps the responses it had
already fetched, which is what makes a payload failure diagnosable afterwards.

The failure is recorded by the Pipeline Run, not here, so the one-off `ingest` command
leaves the same trace. What this module still owns is the schedule: whatever went wrong,
the next cycle happens.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from nazarenow.cycle import INTERVAL_SECONDS, STALE_AFTER_SECONDS
from nazarenow.pipeline import run_pipeline
from nazarenow.store import Store

# Both live in `cycle`, which neither reads a provider nor serves a request, so the
# read-only API can learn the staleness threshold without importing this module and the
# network call behind it.
__all__ = ["INTERVAL_SECONDS", "STALE_AFTER_SECONDS", "run_scheduled"]


def run_scheduled(
    store: Store,
    client: httpx.Client,
    *,
    runs: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    interval: float = INTERVAL_SECONDS,
) -> list[bool]:
    """Run the pipeline every `interval` seconds, returning whether each run succeeded.

    Runs immediately, then waits. Sleeping first would leave a freshly started scheduler
    serving nothing — or three-hour-old data — for a full cycle after every restart, which
    is exactly when someone is most likely to be watching.

    `runs` bounds the loop; None means forever, which is what the CLI passes.

    `sleep` covers **every** wait this loop performs: the cycle interval, and the retry
    backoff inside a Pipeline Run. Forwarding it was not optional bookkeeping — an earlier
    version passed it only to the interval, so the suite really did sit through the
    provider backoff of every failing run and took 25 seconds, while the test module's own
    docstring claimed it exercised the cadence "without sleeping through it". A slow suite
    is a suite people stop running.
    """
    completed: list[bool] = []

    while runs is None or len(completed) < runs:
        if completed:
            sleep(interval)

        try:
            run_pipeline(store, client, sleep=sleep)
        except Exception as error:  # noqa: BLE001 — surviving the unanticipated is the job
            # Both the kind and the detail: "failed" alone cannot distinguish a provider
            # outage from a payload this system has stopped understanding, and those need
            # very different responses from whoever reads the log.
            print(f"Pipeline Run failed: {type(error).__name__}: {error}", flush=True)
            completed.append(False)
            continue

        latest = store.latest_conditions()
        observed = latest["observed_at"] if latest else "unknown"
        print(f"Pipeline Run stored conditions observed at {observed}", flush=True)
        completed.append(True)

    return completed
