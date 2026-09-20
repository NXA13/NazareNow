"""Trace the sampled bathymetry into simplified SVG contour paths.

**This is the map's build step (#121), promoted out of `prototypes/v2-map/`.** Run it with
`npm run map`, which writes `src/map-geometry.json` for the page to import. It is manual and
its output is committed, exactly like `npm run fonts` -- the difference being that this one
needs no network at all, only the soundings committed beside it.

Marching squares over the grid, one pass per depth level, then Ramer-Douglas-Peucker to
cut the point count down. No numpy: the grid is 106 x 121, and plain Python traces the whole
thing in well under a second.

The output is deliberately coordinates-in-a-viewBox rather than lon/lat, because nothing
downstream reprojects anything -- the map is one fixed frame of one fixed place. The
projection is equirectangular with the longitude axis scaled by cos(latitude), which at
0.65 degrees of latitude is indistinguishable from a proper conformal projection and
does not need a library.

Land is emitted as a single even-odd path: the mainland closed along the eastern edge of
the frame, plus any closed loop at the zero contour -- which at this location means the
Lagoa de Obidos, a real lagoon that would otherwise be painted as dry land.
"""

from __future__ import annotations

import base64
import json
import math
import struct
from pathlib import Path

HERE = Path(__file__).parent
GRID = json.loads((HERE / "bathymetry.json").read_text(encoding="utf-8"))

VIEW_H = 780.0

# Depth levels, closer together over the shelf than in the abyss. The canyon reads as a
# canyon because its walls cross many levels in a short distance; spacing them evenly in
# metres would spend most of the lines on flat deep water where nothing happens.
# Re-cut for the zoomed frame. Its deepest point is around 1800 m, and the shelf either
# side of the canyon head sits between 50 and 200 m, so the levels crowd where the walls
# are and thin out below them.
LEVELS = [-1800, -1600, -1400, -1200, -1000, -850, -700, -575, -460,
          -360, -280, -210, -155, -110, -75, -45, -20]

# How far a simplified contour may sit from the traced one, in viewBox pixels.
#
# **Raised from 0.9 to 2.0 by #121, and it costs no accuracy at all.** One pixel is 59.9 m
# across this frame, so 0.9 px is a 54 m tolerance -- asserted over soundings that are
# 0.004 degrees apart, which at this latitude is about 342 m. A contour's position between two
# samples 342 m apart is interpolation; holding it to 54 m is precision the data does not have.
#
# 2.0 px is 120 m, roughly a third of a grid cell, so nothing true is discarded. Measured
# across the whole sweep, the traced path count is **33 at every tolerance from 0.9 to 2.5** --
# no contour, no seamount and no canyon wall is ever dropped, only vertex density changes. What
# it buys is 31% of the bytes: 7.46 kB gzipped at 0.9, 5.16 kB at 2.0.
#
# So this is not a fidelity-for-bytes trade. It is declining to ship false precision, and being
# paid for it. Anything past ~2.9 px would exceed half a grid cell and should not be taken
# without re-measuring against the soundings.
SIMPLIFY_PX = 2.0
MIN_POINTS = 4
MIN_SPAN_PX = 9.0


def view_width() -> float:
    lat_mid = (GRID["lat_top"] + GRID["lat_bottom"]) / 2
    lon_span = (GRID["lon_right"] - GRID["lon_left"]) * math.cos(math.radians(lat_mid))
    lat_span = GRID["lat_top"] - GRID["lat_bottom"]
    return VIEW_H * lon_span / lat_span


VIEW_W = view_width()


def to_view(col: float, row: float) -> tuple[float, float]:
    """Grid indices (fractional) to viewBox pixels. Row 0 is the northern edge."""
    x = col / (GRID["cols"] - 1) * VIEW_W
    y = row / (GRID["rows"] - 1) * VIEW_H
    return x, y


def segments_at(level: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Marching squares: every cell contributes 0, 1 or 2 segments of the isoline."""
    z = GRID["elevation_m"]
    out = []

    def interp(ca: float, ra: float, va: float, cb: float, rb: float, vb: float):
        if vb == va:
            t = 0.5
        else:
            t = (level - va) / (vb - va)
        return to_view(ca + (cb - ca) * t, ra + (rb - ra) * t)

    for r in range(GRID["rows"] - 1):
        for c in range(GRID["cols"] - 1):
            tl, tr = z[r][c], z[r][c + 1]
            bl, br = z[r + 1][c], z[r + 1][c + 1]
            if None in (tl, tr, bl, br):
                continue

            index = (1 if tl > level else 0) | (2 if tr > level else 0) \
                | (4 if br > level else 0) | (8 if bl > level else 0)
            if index in (0, 15):
                continue

            top = interp(c, r, tl, c + 1, r, tr)
            right = interp(c + 1, r, tr, c + 1, r + 1, br)
            bottom = interp(c, r + 1, bl, c + 1, r + 1, br)
            left = interp(c, r, tl, c, r + 1, bl)

            if index in (1, 14):
                out.append((left, top))
            elif index in (2, 13):
                out.append((top, right))
            elif index in (3, 12):
                out.append((left, right))
            elif index in (4, 11):
                out.append((right, bottom))
            elif index in (6, 9):
                out.append((top, bottom))
            elif index in (7, 8):
                out.append((left, bottom))
            elif index == 5:
                out.append((left, top))
                out.append((right, bottom))
            elif index == 10:
                out.append((top, right))
                out.append((left, bottom))
    return out


def key(point: tuple[float, float]) -> tuple[int, int]:
    return (round(point[0] * 64), round(point[1] * 64))


def join(segments) -> list[list[tuple[float, float]]]:
    """Walk the segment soup into polylines, following shared endpoints."""
    adjacency: dict[tuple[int, int], list[int]] = {}
    for i, (a, b) in enumerate(segments):
        adjacency.setdefault(key(a), []).append(i)
        adjacency.setdefault(key(b), []).append(i)

    used = [False] * len(segments)
    paths = []

    def walk(start_index: int, from_end: bool) -> list[tuple[float, float]]:
        a, b = segments[start_index]
        head, tail = (b, a) if from_end else (a, b)
        used[start_index] = True
        chain = [head, tail]
        while True:
            candidates = [i for i in adjacency.get(key(chain[-1]), []) if not used[i]]
            if not candidates:
                return chain
            i = candidates[0]
            used[i] = True
            a, b = segments[i]
            chain.append(b if key(a) == key(chain[-1]) else a)

    # Open ends first, so an isoline that leaves the frame is traced whole rather than
    # split in two at whatever segment happened to be visited first.
    ends = {k: v for k, v in adjacency.items() if len(v) == 1}
    for k, indices in ends.items():
        i = indices[0]
        if used[i]:
            continue
        a, b = segments[i]
        paths.append(walk(i, key(b) == k))

    for i in range(len(segments)):
        if not used[i]:
            paths.append(walk(i, False))
    return paths


def simplify(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker, iterative so a long coastline cannot blow the stack."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        worst, worst_at = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i]
            if norm == 0:
                distance = math.hypot(px - ax, py - ay)
            else:
                distance = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if distance > worst:
                worst, worst_at = distance, i
        if worst > epsilon and worst_at > 0:
            keep[worst_at] = True
            stack.append((first, worst_at))
            stack.append((worst_at, last))
    return [p for p, k in zip(points, keep) if k]


def path_data(points: list[tuple[float, float]], closed: bool) -> str:
    head = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    rest = "".join(f"L{x:.1f},{y:.1f}" for x, y in points[1:])
    return head + rest + ("Z" if closed else "")


def is_closed(points) -> bool:
    return key(points[0]) == key(points[-1])


def span(points) -> float:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def trace(level: float, epsilon: float = SIMPLIFY_PX) -> list[str]:
    paths = []
    for chain in join(segments_at(level)):
        closed = is_closed(chain)
        reduced = simplify(chain, epsilon)
        if len(reduced) < MIN_POINTS or span(reduced) < MIN_SPAN_PX:
            continue
        paths.append(path_data(reduced, closed))
    return paths


def land_path() -> str:
    """One even-odd path: mainland closed along the east edge, lagoons as holes."""
    chains = [c for c in join(segments_at(0.0)) if span(c) > MIN_SPAN_PX]
    chains.sort(key=span, reverse=True)

    pieces = []
    for chain in chains:
        reduced = simplify(chain, 0.6)
        if len(reduced) < MIN_POINTS:
            continue
        if is_closed(reduced):
            # An island, or -- with the even-odd fill -- a lagoon punched back out of the
            # land. Small loops at this resolution are sounding noise, not geography.
            if span(reduced) >= 22.0:
                pieces.append(path_data(reduced, True))
            continue
        # An open chain is a stretch of coast that leaves the frame. Closing it straight
        # from its last point back to its first draws a teardrop out in open water, which
        # is what the first render did; close it around the EAST edge instead, so the fill
        # lands on the dry side where it belongs.
        if span(reduced) < 60.0:
            continue
        first, last = reduced[0], reduced[-1]
        reduced = reduced + [(VIEW_W + 40, last[1]), (VIEW_W + 40, first[1])]
        pieces.append(path_data(reduced, True))
    return "".join(pieces)


# The levels that become filled bands, shallow to deep, and the only ones the page draws.
#
# **This list is what ships.** The tracer knows seventeen levels; eight of them become bands and
# the other nine were emitted, downloaded and never drawn — 42% of the geometry's bytes, against
# a payload budget this ticket had to raise. `LEVELS` stays as it is because the spacing is what
# makes the canyon read as a canyon, and a band list cut from it is cheaper than re-cutting the
# trace every time the design wants a different eight.
BANDS = [-20, -75, -155, -280, -460, -700, -1000, -1400]


def perimeter_t(point: tuple[float, float]) -> float | None:
    """Where a point sits on the frame's edge, as a number from 0 to 4 going clockwise from
    the north-west corner, or None if it is not on the edge at all."""
    x, y = point
    if abs(y) <= 0.6:
        return x / VIEW_W
    if abs(x - VIEW_W) <= 0.6:
        return 1 + y / VIEW_H
    if abs(y - VIEW_H) <= 0.6:
        return 2 + (VIEW_W - x) / VIEW_W
    if abs(x) <= 0.6:
        return 3 + (VIEW_H - y) / VIEW_H
    return None


def corner(t: int) -> tuple[float, float]:
    return [(0.0, 0.0), (VIEW_W, 0.0), (VIEW_W, VIEW_H), (0.0, VIEW_H)][t % 4]


def _between(start: float, end: float, point: float, forward: bool) -> bool:
    reach = (end - start) % 4 if forward else (start - end) % 4
    here = (point - start) % 4 if forward else (start - point) % 4
    return 0 < here < reach


def close_on_frame(points: list[tuple[float, float]]) -> str:
    """Close an open contour by walking the frame's edge, on the deep side.

    **A band is "everything deeper than this level", so the closure has to enclose the deep
    water** — and which way round the frame that is depends on where the contour leaves it.
    Closing every open contour westward was the first attempt and it is wrong for two of the
    eight bands: at -20 the contour enters on the east edge and leaves on the south, and a
    straight closure cuts a chord across the frame at y=14.9 that drops the whole top strip out
    of the band. At -75 it enters on the north edge.

    This is prototype defect 3 in its other form. That one was about the coastline closing
    end-to-start and drawing a teardrop out at sea; this is the same mistake one level up — a
    closure that assumes it knows which edge a line left through.

    Deep water is west across this whole frame: the canyon opens seaward and the shelf is against
    the coast in the east. So of the two ways round the perimeter, the correct one is whichever
    passes along the western edge.
    """
    start, end = perimeter_t(points[0]), perimeter_t(points[-1])
    if start is None or end is None:
        # Not an edge-to-edge contour. Nothing sensible to walk, so close it as it lies.
        return path_data(points, True)

    forward = _between(end, start, 3.5, True)
    walked = [
        corner(c) for c in range(4) if _between(end, start, float(c), forward)
    ] if forward else [
        corner(c) for c in range(3, -1, -1) if _between(end, start, float(c), forward)
    ]
    return path_data(points + walked, True)


def band(level: float) -> str:
    """One level's contours, each closed against the frame, as a single filled path."""
    pieces = []
    for chain in join(segments_at(level)):
        reduced = simplify(chain, SIMPLIFY_PX)
        if len(reduced) < MIN_POINTS or span(reduced) < MIN_SPAN_PX:
            continue
        pieces.append(
            path_data(reduced, True) if is_closed(reduced) else close_on_frame(reduced)
        )
    return "".join(pieces)


def packed_depth_grid() -> dict:
    """The soundings themselves, for the refraction solve that runs in the page (ADR 0016).

    The contours below are a *drawing* of this grid and cannot be solved over; the solve needs
    every reading. Shipped as little-endian int16 deltas in base64 — 11.00 kB gzipped against
    13.72 kB as JSON numbers, because neighbouring soundings are close in value and that is
    what gzip is good at.

    Metres, rounded to whole metres, sign as stored: negative below sea level. One metre and
    not five: celerity is sqrt(g*d), so a five-metre quantum is a 50% speed error in ten metres
    of water, which is precisely the shoaling zone the map exists to explain.

    `src/depth-grid.ts` is the other half. The round trip is checked here rather than trusted.
    """
    values = [int(round(v)) for row in GRID["elevation_m"] for v in row]
    deltas = [values[0]] + [values[i] - values[i - 1] for i in range(1, len(values))]
    packed = struct.pack(f"<{len(deltas)}h", *deltas)

    running, restored = 0, []
    for d in struct.unpack(f"<{len(deltas)}h", packed):
        running += d
        restored.append(running)
    if restored != values:
        raise SystemExit("depth grid does not survive its own round trip")

    # The frame's scale travels with the grid, because the solve needs metres and the viewBox
    # is in view units. Derived here, from the same soundings, so the page cannot hold a
    # different opinion about how big the frame is than the tracer does.
    metres_per_unit = (GRID["lat_top"] - GRID["lat_bottom"]) * 111_320.0 / VIEW_H

    return {
        "rows": GRID["rows"],
        "cols": GRID["cols"],
        "viewWidth": round(VIEW_W, 1),
        "viewHeight": round(VIEW_H, 1),
        "metresPerUnit": round(metres_per_unit, 6),
        "deltas": base64.b64encode(packed).decode("ascii"),
    }


def main() -> None:
    flat = [v for row in GRID["elevation_m"] for v in row if v is not None]
    print(f"viewBox 0 0 {VIEW_W:.0f} {VIEW_H:.0f}")
    print(f"depth range {min(flat):.0f} m to {max(flat):.0f} m")

    out = {
        "viewBox": f"0 0 {VIEW_W:.1f} {VIEW_H:.1f}",
        # Shallow to deep, and the order is load-bearing: each band fills everything deeper than
        # its level, so painted in this order the deepest water is the last thing drawn.
        "bands": [{"level": level, "d": band(level)} for level in BANDS],
        "levels": {},
        "land": land_path(),
    }
    total = sum(len(b["d"]) for b in out["bands"])
    for level in BANDS:
        paths = trace(level)
        out["levels"][str(level)] = paths
        size = sum(len(p) for p in paths)
        total += size
        print(f"  {level:>6} m  {len(paths):>3} paths  {size:>6} chars")
    print(f"land path {len(out['land'])} chars")
    print(f"total {total + len(out['land'])} chars of path data")

    # Into the app, not beside this script. The page imports it; nothing regenerates it at
    # build time and nothing needs a network to.
    destination = HERE.parents[1] / "src" / "map-geometry.json"
    destination.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {destination.relative_to(HERE.parents[2])}")

    grid = packed_depth_grid()
    grid_destination = HERE.parents[1] / "src" / "depth-grid.json"
    grid_destination.write_text(json.dumps(grid, separators=(",", ":")), encoding="utf-8")
    print(
        f"wrote {grid_destination.relative_to(HERE.parents[2])} "
        f"({grid['rows']}x{grid['cols']} soundings, {len(grid['deltas'])} chars of base64)"
    )


if __name__ == "__main__":
    main()
