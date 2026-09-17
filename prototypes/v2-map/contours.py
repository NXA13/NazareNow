"""Trace the sampled bathymetry into simplified SVG contour paths.

Marching squares over the grid, one pass per depth level, then Ramer-Douglas-Peucker to
cut the point count down to something a 140 kB payload budget can carry. No numpy: the
grid is 82 x 96, and plain Python traces the whole thing in well under a second.

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

import json
import math
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

SIMPLIFY_PX = 0.9
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


def to_path(points: list[tuple[float, float]], closed: bool) -> str:
    body = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f"M{body.replace(' ', ' L', 1) if False else body}"


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


def main() -> None:
    flat = [v for row in GRID["elevation_m"] for v in row if v is not None]
    print(f"viewBox 0 0 {VIEW_W:.0f} {VIEW_H:.0f}")
    print(f"depth range {min(flat):.0f} m to {max(flat):.0f} m")

    out = {"viewBox": f"0 0 {VIEW_W:.1f} {VIEW_H:.1f}", "levels": {}, "land": land_path()}
    total = 0
    for level in LEVELS:
        paths = trace(level)
        out["levels"][str(level)] = paths
        size = sum(len(p) for p in paths)
        total += size
        print(f"  {level:>6} m  {len(paths):>3} paths  {size:>6} chars")
    print(f"land path {len(out['land'])} chars")
    print(f"total {total + len(out['land'])} chars of path data")

    (HERE / "contours.json").write_text(json.dumps(out), encoding="utf-8")


if __name__ == "__main__":
    main()
