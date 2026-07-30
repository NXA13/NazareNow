"""Run the pipeline from the command line, once or on the forecast cycle.

    python -m nazarenow ingest      one run, then exit
    python -m nazarenow schedule    a run every three hours, forever

`ingest` is how a bad prediction gets reproduced: the same code path the schedule uses,
run by hand against the same store. `schedule` is what ADR 0005 asks for, and what a
deployed instance runs.
"""

from __future__ import annotations

import os
import sys

import httpx

from nazarenow.pipeline import run_pipeline
from nazarenow.schedule import INTERVAL_SECONDS, run_scheduled
from nazarenow.store import Store


def ingest() -> int:
    # Same default the API uses, anchored to the repository rather than the working
    # directory, so ingesting and serving cannot end up on different databases.
    store = Store(os.environ.get("NAZARENOW_DB") or None)
    with httpx.Client() as client:
        run_pipeline(store, client)

    latest = store.latest_conditions()
    assert latest is not None  # a successful run always writes conditions
    print(f"Stored conditions observed at {latest['observed_at']}")
    for name, reading in sorted(latest["readings"].items()):
        print(f"  {name:<18} {reading['value']:>7} {reading['unit']}")
    return 0


def schedule() -> int:
    """Run forever, on the forecast cycle.

    Returns only if interrupted. A failed run is logged and the schedule continues, so
    this exits on Ctrl-C or a signal rather than on a provider outage.
    """
    store = Store(os.environ.get("NAZARENOW_DB") or None)
    print(f"Scheduling a Pipeline Run every {INTERVAL_SECONDS // 3600} hours.", flush=True)
    try:
        with httpx.Client() as client:
            run_scheduled(store, client)
    except KeyboardInterrupt:
        print("Stopped.", flush=True)
    return 0


COMMANDS = {"ingest": ingest, "schedule": schedule}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
