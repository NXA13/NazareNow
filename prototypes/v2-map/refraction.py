"""Wave fronts that bend the way the sea bends them.

Straight crest lines ruled across the map are a lie about the one thing this site exists
to explain. A swell arriving at Nazare does not stay straight: in water shallower than
about half its wavelength it slows, and a front travelling partly over the shelf and
partly over the canyon bends towards the slow side. The canyon, being deep, stays fast --
so the fronts either side of it lag, the front wraps around the canyon head, and the
energy that should have spread along ten kilometres of beach arrives at one peak. That
convergence IS the wave. Drawing it is worth more than any amount of styling.

The model here is the schoolbook one and is named as such wherever it is shown:

    celerity  c = min(c_deep, sqrt(g * depth))      c_deep = g * T / 2*pi

Travel time from the open ocean is then a shortest-path problem over the depth grid --
Dijkstra with eight neighbours, cost = distance / celerity -- seeded with a straight
plane wave on the upwind edges. Crests are isochrones of that field, so they bend, stall
and wrap for exactly the reason real ones do. Animating means stepping the phase.

What this is NOT: a spectral wave model. It ignores diffraction, reflection, currents,
non-linearity and the fact that a real swell is a spread of periods and directions rather
than one. It is a picture of refraction alone, at one period, and the caption says so.

Crest SPACING is exaggerated. A 13.75 s swell has a 295 m wavelength in deep water, which
over a 65 km frame would be two hundred crests and a moire pattern. The spacing here is
chosen so the fronts are legible; their SHAPE, which is the informative part, is honest.
"""

from __future__ import annotations

import base64
import heapq
import json
import math
import struct
import sys
from pathlib import Path

# `contours.py` was promoted into `frontend/scripts/map/` by #121, where the build step that
# ships the map can own it, so there is one tracer rather than two. The path goes on `sys.path`
# before `contours` is imported, which is why this sits above the import rather than beside the
# other constants. The soundings no longer come from `bathymetry.json` beside it — see below.
PROMOTED = Path(__file__).resolve().parents[2] / "frontend" / "scripts" / "map"
sys.path.insert(0, str(PROMOTED))

from contours import join, path_data, simplify  # noqa: E402

HERE = Path(__file__).parent

# **The soundings come from the file the page ships, not from `bathymetry.json`.**
# This file is the reference implementation the browser port is pinned against
# (ADR 0016, `frontend/src/refraction.parity.test.ts`), and a reference that reads different
# inputs is not a reference. The shipped grid is rounded to whole metres; reading the raw
# floats here moved 30 of 381 crests by up to 6.7 view units — not by drifting, but because a
# near-straight crest's Douglas-Peucker arg-max flips between two nearly-equidistant points
# under the smallest nudge. One grid, one answer.
PACKED = json.loads((HERE.parents[1] / "frontend" / "src" / "depth-grid.json").read_text(encoding="utf-8"))

VIEW_W, VIEW_H = PACKED["viewWidth"], PACKED["viewHeight"]
ROWS, COLS = PACKED["rows"], PACKED["cols"]


def _unpack_soundings() -> list[list[int]]:
    deltas = struct.unpack(f"<{ROWS * COLS}h", base64.b64decode(PACKED["deltas"]))
    flat, running = [], 0
    for d in deltas:
        running += d
        flat.append(running)
    return [flat[r * COLS : (r + 1) * COLS] for r in range(ROWS)]


Z = _unpack_soundings()

G = 9.81
FRAMES = 16
CREST_SPACING_PX = 38.0


# Derived by `scripts/map/contours.py` from the same soundings and shipped beside them, so the
# page and this file cannot hold different opinions about how big the frame is.
M_PER_PX = PACKED["metresPerUnit"]


def to_view(col: float, row: float) -> tuple[float, float]:
    return col / (COLS - 1) * VIEW_W, row / (ROWS - 1) * VIEW_H


def celerity_grid(period: float) -> list[list[float | None]]:
    """Wave speed at every wet cell; None on land, which blocks the front entirely."""
    deep = G * period / (2 * math.pi)
    out: list[list[float | None]] = []
    for r in range(ROWS):
        row: list[float | None] = []
        for c in range(COLS):
            elevation = Z[r][c]
            if elevation is None or elevation >= 0:
                row.append(None)
            else:
                # A 2 m floor keeps the shore cells from costing infinity and stalling
                # the whole front on one pixel of surf zone.
                row.append(min(deep, math.sqrt(G * max(-elevation, 2.0))))
        out.append(row)
    return out


def travel_time(period: float, heading_deg: float) -> list[list[float | None]]:
    """Seconds since the plane wave crossed the upwind corner of the frame."""
    c = celerity_grid(period)
    deep = G * period / (2 * math.pi)

    # Direction of travel in grid pixels: x east, y south.
    dx = math.sin(math.radians(heading_deg))
    dy = -math.cos(math.radians(heading_deg))

    px_per_col = VIEW_W / (COLS - 1)
    px_per_row = VIEW_H / (ROWS - 1)

    best: list[list[float]] = [[math.inf] * COLS for _ in range(ROWS)]
    queue: list[tuple[float, int, int]] = []

    # Seed every cell on the two upwind edges with the time a straight front would
    # reach it, so the front enters the frame flat and only the sea bends it.
    for r in range(ROWS):
        for col in range(COLS):
            on_edge = (r == 0 and dy > 0) or (r == ROWS - 1 and dy < 0) \
                or (col == 0 and dx > 0) or (col == COLS - 1 and dx < 0)
            if not on_edge or c[r][col] is None:
                continue
            x, y = col * px_per_col, r * px_per_row
            t = (x * dx + y * dy) * M_PER_PX / deep
            if t < best[r][col]:
                best[r][col] = t
                heapq.heappush(queue, (t, r, col))

    # Normalise so the earliest seed is zero; the absolute datum is meaningless.
    if queue:
        offset = min(t for t, _, _ in queue)
        for r in range(ROWS):
            for col in range(COLS):
                if best[r][col] != math.inf:
                    best[r][col] -= offset
        queue = [(t - offset, r, col) for t, r, col in queue]
        heapq.heapify(queue)

    neighbours = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    while queue:
        t, r, col = heapq.heappop(queue)
        if t > best[r][col]:
            continue
        here = c[r][col]
        for dr, dc in neighbours:
            nr, nc = r + dr, col + dc
            if not (0 <= nr < ROWS and 0 <= nc < COLS):
                continue
            there = c[nr][nc]
            if there is None:
                continue
            step = math.hypot(dr * px_per_row, dc * px_per_col) * M_PER_PX
            # Average the two speeds: a front crossing a steep canyon wall spends half
            # the step in each, and using only the destination's speed makes the wall
            # itself a discontinuity the isochrones then trace as a false crest.
            candidate = t + step / ((here + there) / 2)
            if candidate < best[nr][nc]:
                best[nr][nc] = candidate
                heapq.heappush(queue, (candidate, nr, nc))

    return [[None if v == math.inf else v for v in row] for row in best]


def isochrone_segments(field: list[list[float | None]], level: float) -> list:
    """Marching squares over the travel-time field: one crest at one instant, as loose segments.

    Split out of `isochrone` so the crests can be inspected before simplification decides
    which of them survive. The port in `frontend/src/refraction.ts` is checked against this
    file, and a question about *which chains are dropped* cannot be asked of path strings.
    """
    segments = []

    def interp(ca, ra, va, cb, rb, vb):
        t = 0.5 if vb == va else (level - va) / (vb - va)
        return to_view(ca + (cb - ca) * t, ra + (rb - ra) * t)

    for r in range(ROWS - 1):
        for col in range(COLS - 1):
            tl, tr = field[r][col], field[r][col + 1]
            bl, br = field[r + 1][col], field[r + 1][col + 1]
            if None in (tl, tr, bl, br):
                continue
            index = (1 if tl > level else 0) | (2 if tr > level else 0) \
                | (4 if br > level else 0) | (8 if bl > level else 0)
            if index in (0, 15):
                continue
            top = interp(col, r, tl, col + 1, r, tr)
            right = interp(col + 1, r, tr, col + 1, r + 1, br)
            bottom = interp(col, r + 1, bl, col + 1, r + 1, br)
            left = interp(col, r, tl, col, r + 1, bl)
            if index in (1, 14):
                segments.append((left, top))
            elif index in (2, 13):
                segments.append((top, right))
            elif index in (3, 12):
                segments.append((left, right))
            elif index in (4, 11):
                segments.append((right, bottom))
            elif index in (6, 9):
                segments.append((top, bottom))
            elif index in (7, 8):
                segments.append((left, bottom))
            elif index == 5:
                segments.append((left, top))
                segments.append((right, bottom))
            elif index == 10:
                segments.append((top, right))
                segments.append((left, bottom))

    return segments


# A chain shorter than two grid cells is an artefact of the tracer rather than a front: the
# soundings are about 342 m apart and nothing smaller than a couple of cells is resolved by
# them. This replaced a `len(reduced) < 3` test, which used vertex count as a proxy for length
# and got it backwards — a crest that is perfectly STRAIGHT simplifies to two points, so the
# old rule discarded 83 real fragments across a 16-frame loop, the longest of them 67.5 view
# units (about 4 km of front), and dropped every crest of a flat sea entirely.
MIN_CREST_LENGTH = 2 * math.hypot(VIEW_W / (COLS - 1), VIEW_H / (ROWS - 1))


def chain_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def isochrone(field: list[list[float | None]], level: float) -> list[str]:
    """One crest at one instant, simplified and formatted as SVG path data."""
    paths = []
    for chain in join(isochrone_segments(field, level)):
        if chain_length(chain) < MIN_CREST_LENGTH:
            continue
        reduced = simplify(chain, 0.7)
        if len(reduced) < 2:
            continue
        paths.append(path_data(reduced, False))
    return paths


def crest_frames(period: float, heading_deg: float) -> dict:
    field = travel_time(period, heading_deg)
    finite = [v for row in field for v in row if v is not None]
    span = max(finite)

    deep = G * period / (2 * math.pi)
    interval = CREST_SPACING_PX * M_PER_PX / deep  # seconds between drawn crests

    frames = []
    for frame in range(FRAMES):
        phase = frame / FRAMES * interval
        paths = []
        level = phase
        while level < span:
            paths.extend(isochrone(field, level))
            level += interval
        frames.append(paths)
    return {
        "viewBox": f"0 0 {VIEW_W} {VIEW_H}",
        "period_s": period,
        "from_direction_deg": (heading_deg + 180) % 360,
        "frames": frames,
    }


def main() -> None:
    # The gold-day sea: 13.75 s from 310 degrees, so travelling towards 130.
    data = crest_frames(13.75, 130.0)
    size = sum(len(p) for frame in data["frames"] for p in frame)
    print(f"{FRAMES} frames, {sum(len(f) for f in data['frames'])} paths, {size} chars")
    (HERE / "crests.json").write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    main()
