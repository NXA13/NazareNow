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

Nothing is written by a failed run. `Store.record_run` is a single transaction, so the
previous conditions, forecast and calls stay exactly as they were, and the interface marks
them stale rather than presenting them as fresh.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from nazarenow.pipeline import run_pipeline
from nazarenow.store import Store

# Three hours, in seconds. See the module docstring for why this number and not six.
INTERVAL_SECONDS = 3 * 60 * 60

# When results stop being presentable as current: two whole cycles without a successful
# run. One missed run is a blip — a provider hiccup, a restart — and calling that stale
# would train users to ignore the warning. Two means something is actually wrong.
#
# It lives beside the interval rather than in the API, so a change to the cadence cannot
# leave the staleness threshold describing a schedule that no longer exists.
STALE_AFTER_SECONDS = 2 * INTERVAL_SECONDS


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

    `runs` bounds the loop; None means forever, which is what the CLI passes. The tests
    bound it, and `sleep` is injected so they exercise the cadence without waiting for it.
    """
    completed: list[bool] = []

    while runs is None or len(completed) < runs:
        if completed:
            sleep(interval)

        try:
            run_pipeline(store, client)
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
