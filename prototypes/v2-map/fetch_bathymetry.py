"""Sample GEBCO 2020 depths around the Nazare Canyon into a regular grid.

Open Topo Data serves the GEBCO 2020 global bathymetry as a point-lookup API, 100
locations per request, one request per second. That is enough to build the grid the
map's contours are traced from, and it is the same shape the shipped map would use:
sample once, store the result, never ask the provider again at render time.

The grid is deliberately small. A map that has to load on a Raspberry Pi over a home
connection cannot carry a raster relief, so what ships is a handful of simplified
contour paths -- and contours do not need a dense grid to be traced, they need a grid
fine enough that the canyon walls do not alias into staircases. 0.008 degrees is about
900 m north-south and 680 m east-west at this latitude, against GEBCO's own 15
arc-second (~460 m) resolution: half the source detail, which the simplifier would
throw away regardless.

Writes a JSON grid so the contouring step can be re-run without re-fetching.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The head of the canyon and the shelf either side of it. Not the whole 230 km feature:
# the site's map is about where the waves break, and the last 60 km of canyon is what
# focuses them. Aspect is chosen to sit in a tall panel beside the forecast column.
# Tightened onto the canyon head after the first, wider sample proved the feature was
# legible in the data but too small in frame to read as a canyon at panel size. Sampled at
# GEBCO's own resolution here rather than half of it, because a zoomed frame shows the
# staircase that a coarse sample leaves on a steep canyon wall.
LAT_MIN, LAT_MAX = 39.40, 39.82
LON_MIN, LON_MAX = -9.52, -9.04
STEP = 0.004

API = "https://api.opentopodata.org/v1/gebco2020"
BATCH = 100
PAUSE = 1.1  # the public instance allows one call a second; leave headroom.

OUT = Path(__file__).with_name("bathymetry.json")
# Keep the wide sample; it is what proved where the canyon actually is.
WIDE = Path(__file__).with_name("bathymetry-wide.json")


def frange(start: float, stop: float, step: float) -> list[float]:
    """Inclusive float range, built by index so rounding never drops the last row."""
    count = int(round((stop - start) / step)) + 1
    return [round(start + i * step, 6) for i in range(count)]


def fetch(points: list[tuple[float, float]], attempt: int = 1) -> list[float | None]:
    query = "|".join(f"{lat},{lon}" for lat, lon in points)
    request = urllib.request.Request(
        f"{API}?locations={query}",
        headers={"User-Agent": "NazareNow-map-prototype"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        if attempt >= 4:
            raise
        # A rate limit or a blip: back off rather than hammering a free service.
        time.sleep(PAUSE * 4 * attempt)
        return fetch(points, attempt + 1)

    if payload.get("status") != "OK":
        raise RuntimeError(f"Open Topo Data refused the batch: {payload}")
    return [result["elevation"] for result in payload["results"]]


def main() -> int:
    lats = frange(LAT_MIN, LAT_MAX, STEP)
    lons = frange(LON_MIN, LON_MAX, STEP)

    # North at the top of the grid, so row 0 is LAT_MAX and the SVG needs no flip.
    lats = list(reversed(lats))

    flat: list[tuple[float, float]] = [(lat, lon) for lat in lats for lon in lons]
    total = len(flat)
    print(f"{len(lats)} rows x {len(lons)} cols = {total} points, "
          f"{-(-total // BATCH)} requests", file=sys.stderr)

    depths: list[float | None] = []
    for start in range(0, total, BATCH):
        batch = flat[start:start + BATCH]
        depths.extend(fetch(batch))
        done = len(depths)
        print(f"  {done}/{total}", file=sys.stderr)
        if start + BATCH < total:
            time.sleep(PAUSE)

    grid = [depths[r * len(lons):(r + 1) * len(lons)] for r in range(len(lats))]

    OUT.write_text(json.dumps({
        "source": "GEBCO 2020 via Open Topo Data",
        "lat_top": lats[0],
        "lat_bottom": lats[-1],
        "lon_left": lons[0],
        "lon_right": lons[-1],
        "step": STEP,
        "rows": len(lats),
        "cols": len(lons),
        "elevation_m": grid,
    }), encoding="utf-8")
    print(f"wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
