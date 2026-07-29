"""Run a Pipeline Run from the command line.

    python -m nazarenow ingest

Per ADR 0005 this is what a scheduler will invoke; ticket #7 makes it periodic. Until
then it is run by hand, which is also how a bad prediction gets reproduced.
"""

from __future__ import annotations

import os
import sys

import httpx

from nazarenow.pipeline import run_pipeline
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


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] != "ingest":
        print(__doc__)
        return 2
    return ingest()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
