"""The settled readings for the seven features a Predictive Distribution does not perturb.

Ticket #80. `distribution.py` perturbs one of the Amplification Model's eight features — the
incoming Combined Sea — and passes the other seven through untouched. Checking the assembled
distribution against an outcome therefore needs those seven for every hour scored, and
`analysis/forecast_error/download_runs.py` cannot supply them: the marine archive carries no
Swell partition at any Lead Time (ADR 0004's #14 amendment), which is the whole reason they
go unperturbed.

**So they are taken settled, not forecast, and that is a choice with a direction.** The
running system reads a *lead-N* swell partition it cannot archive; this reads Open-Meteo's
own settled analysis for the same hour. That hands the distribution better inputs than the
Pipeline Run had, so it can only make the centre more accurate than the real one — which
makes any under-coverage this measurement finds a **floor** rather than an estimate.
`coverage.py` states it beside every table for that reason.

The plain variables are served for past dates where the `_previous_dayN` suffixed ones come
back null — the negative result `download_runs.probe_archive` records. This module is the
positive half of the same probe.

**Wind and Combined Sea are not fetched here.** Both are already in the forecast archive at
Lead Time 0, which is the same settled reading: `waves()` carries `wave_height` and `wind()`
carries both wind variables. Re-retrieving them would put a second copy of the same hour in
a second cache, and the two could disagree.

`_get` is imported rather than reimplemented. It is thirty lines of retry, backoff and
cache policy toward a free provider the whole project depends on, and a second copy would be
a second policy — free to drift from the one `download_runs.py` documents.

Run:
    .venv/Scripts/python.exe analysis/distribution_coverage/settled.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from download_runs import (  # noqa: E402
    END,
    WAVE_ARCHIVE_START,
    _get,
    _months,
)
from nazarenow.sources.open_meteo import (  # noqa: E402
    LATITUDE,
    LONGITUDE,
    MARINE_READINGS,
    MARINE_URL,
    TIMEZONE,
)

SETTLED_READINGS = MARINE_READINGS
"""The Swell partition, under the reading names the model consumes.

Imported from the running system rather than retyped. `heuristic.predict` reads
`readings["swell_period"]` and the learned model's feature map reads `readings["swell_height"]`
— so a local spelling here would be a second name for the same thing, and the failure would be
a `KeyError` in the middle of a nine-month scoring run rather than at the boundary.
"""


def settled() -> dict[str, dict[str, float]]:
    """`{local hour: {reading: value}}` for the Swell partition, over the archive's span.

    Keyed by the same local-hour strings `Runs` uses, so the join in `coverage.py` is a
    dictionary intersection and not a date parse. An hour the provider returned null for is
    **absent** rather than present-and-None, matching `Runs`: a caller gets a number or a
    `KeyError`, never a null that arithmetic turns into nonsense.
    """
    variables = sorted(set(SETTLED_READINGS.values()))
    by_hour: dict[str, dict[str, float]] = {}

    for start, finish in _months(WAVE_ARCHIVE_START, END):
        body = _get(
            MARINE_URL,
            {
                "latitude": LATITUDE,
                "longitude": LONGITUDE,
                "timezone": TIMEZONE,
                "length_unit": "metric",
                "start_date": start.isoformat(),
                "end_date": finish.isoformat(),
                "hourly": ",".join(variables),
            },
            f"settled_swell_{start:%Y-%m}",
        )
        by_hour.update(_parse(body, f"settled_swell_{start:%Y-%m}"))

    if not by_hour:
        raise RuntimeError("the settled Swell retrieval returned no hours at all")
    return by_hour


def _parse(body: dict[str, Any], name: str) -> dict[str, dict[str, float]]:
    """Validate a response and key it by local hour.

    The timezone check is the same one `download_runs._parse` makes and for the same reason:
    these hours are joined against Lead Time readings counted back from Nazaré local hours
    (ADR 0008), and a response silently returned on GMT would pair every hour with the wrong
    one an hour away, in a variable that changes slowly enough for nothing to look wrong.
    """
    if body.get("timezone") != TIMEZONE:
        raise ValueError(
            f"{name}: Open-Meteo returned timestamps on {body.get('timezone')!r}, not "
            f"{TIMEZONE!r} — every hour would join against the wrong Lead Time reading"
        )

    hourly = body.get("hourly") or {}
    times = hourly.get("time")
    if not times:
        raise ValueError(f"{name}: the response carries no hours")

    found: dict[str, dict[str, float]] = {}
    for index, stamp in enumerate(times):
        readings = {}
        for reading, variable in SETTLED_READINGS.items():
            series = hourly.get(variable)
            if series is None:
                raise ValueError(f"{name}: the response carries no {variable!r}")
            value = series[index]
            if value is None:
                break
            readings[reading] = float(value)
        else:
            # Only an hour carrying every reading is stored. A partial hour cannot be
            # scored — the model takes all eight features or none — and keeping it would
            # push the failure into the scoring loop.
            found[stamp] = readings
    return found


def main() -> int:
    hours = settled()
    print(f"{len(hours):,} settled hours carrying the whole Swell partition")
    first, last = min(hours), max(hours)
    print(f"{first} to {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
