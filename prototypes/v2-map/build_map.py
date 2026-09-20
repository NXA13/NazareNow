"""Assemble the map: depth bands, refracted crests, wind, coast — and preview palettes.

One module builds both the local preview and the artboard markup, so what is reviewed is
exactly what ships into the design canvas.

Layer order matters and is the thing most easily got wrong:

    depth bands -> contour hairlines -> wave crests -> wind -> land -> labels

Land last, because a crest drawn across dry land instantly reads as a bug; and crests
under the coastline rather than over it, because that is where the water is.

The crests are the 16 precomputed phases from refraction.py, stacked and shown one at a
time by CSS. Sixteen steps a cycle is coarse enough to see if you look for it and cheap
enough to carry: the alternative, recomputing the field in the browser every frame, is
what the real implementation would do and is not worth prototyping here.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

# `bathymetry.json` was promoted into `frontend/scripts/map/` by #121, where the build step that
# ships the map can own it, and the traced output now lands in `frontend/src/`. This script reads
# both from there. It imports nothing from `contours`, so unlike `refraction.py` it needs no
# `sys.path` entry — only the paths.
PROMOTED = Path(__file__).resolve().parents[2] / "frontend" / "scripts" / "map"

DATA = json.loads((HERE.parents[1] / "frontend" / "src" / "map-geometry.json").read_text(encoding="utf-8"))
CRESTS = json.loads((HERE / "crests.json").read_text(encoding="utf-8"))

VIEW_W, VIEW_H = (float(v) for v in DATA["viewBox"].split()[2:])
VIEW = f'viewBox="0 0 {VIEW_W:.1f} {VIEW_H:.1f}" preserveAspectRatio="xMidYMid slice"'
FILL = 'style="position:absolute;inset:0;width:100%;height:100%;" aria-hidden="true"'
WEST = -60.0
EAST = None  # filled in below, once VIEW_W is known

# Half the deep-water wavelength of a 13.75 s swell is about 148 m: shallower than that
# is where a front starts to feel the bottom and bend. Brightening the crests inside this
# depth, and only inside it, puts the emphasis exactly where the physics is happening
# instead of spreading it evenly over deep water where the lines are dead straight.
SHOALING_LEVEL = -155

# Shallow to deep. Fewer levels than were traced, and deliberately uneven: the steps that
# matter are the ones the canyon walls cross, and an even ramp spends its contrast on
# open shelf where nothing is happening.
BANDS = [-20, -75, -155, -280, -460, -700, -1000, -1400]

CYCLE_S = 2.4


def close_west(path: str) -> str:
    if path.endswith("Z"):
        return path
    points = path[1:].replace("L", " ").split()
    first, last = points[0].split(","), points[-1].split(",")
    return f"{path}L{WEST},{last[1]}L{WEST},{first[1]}Z"


def band_paths(level: int) -> str:
    return "".join(close_west(p) for p in DATA["levels"].get(str(level), []))


def close_east(path: str) -> str:
    """Close a contour around the eastern edge, to fill the SHALLOW side of it."""
    if path.endswith("Z"):
        return path
    points = path[1:].replace("L", " ").split()
    first, last = points[0].split(","), points[-1].split(",")
    edge = VIEW_W + 60
    return f"{path}L{edge},{last[1]}L{edge},{first[1]}Z"


def shoaling_paths() -> str:
    return "".join(close_east(p) for p in DATA["levels"].get(str(SHOALING_LEVEL), []))


def mix(a: str, b: str, t: float) -> str:
    ai = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    bi = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ai, bi))


def depth_svg(palette: dict) -> str:
    deep, shelf = palette["deep"], palette["shelf"]
    out = [f"<svg {VIEW} {FILL}>",
           f'<rect x="0" y="0" width="{VIEW_W:.1f}" height="{VIEW_H:.1f}" fill="{deep}"></rect>']

    # Shallowest first: each level fills everything DEEPER than it, so painting in this
    # order leaves the trench as the last and darkest thing drawn.
    for index, level in enumerate(BANDS):
        t = (1.0 - index / (len(BANDS) - 1)) ** 0.72
        # Even-odd, not nonzero. A band is "everything deeper than this level", and a
        # closed contour inside it is a rise -- a seamount, or the shoulder between the
        # canyon and the shelf. Filled with nonzero it paints as a dark blob out in open
        # water; with even-odd it correctly becomes a hole in the band.
        out.append(f'<path d="{band_paths(level)}" fill-rule="evenodd" '
                   f'fill="{mix(deep, shelf, t)}"></path>')

    for level in BANDS:
        paths = "".join(DATA["levels"].get(str(level), []))
        if paths:
            out.append(f'<path d="{paths}" fill="none" stroke="{palette["hairline"]}" '
                       'stroke-width="0.6" stroke-linejoin="round"></path>')
    out.append("</svg>")
    return "".join(out)


def crest_svg(palette: dict, prefix: str) -> str:
    """Every phase of the front, twice: dim over deep water, bright over the shelf."""
    frames = CRESTS["frames"]
    out = [f"<svg {VIEW} {FILL}>",
           f'<defs><clipPath id="{prefix}-shoal" clip-rule="evenodd">'
           f'<path d="{shoaling_paths()}" clip-rule="evenodd"></path></clipPath></defs>']
    for index, paths in enumerate(frames):
        delay = -CYCLE_S * index / len(frames)
        body = "".join(f'<path d="{d}"></path>' for d in paths)
        out.append(
            f'<g class="{prefix}-crest" style="animation-delay:{delay:.3f}s">'
            f'<g fill="none" stroke="{palette["swell"]}" stroke-width="0.9" '
            f'stroke-linecap="round" opacity="0.22">{body}</g>'
            f'<g fill="none" stroke="{palette["swell"]}" stroke-width="1.5" '
            f'stroke-linecap="round" clip-path="url(#{prefix}-shoal)">{body}</g>'
            "</g>"
        )
    out.append("</svg>")
    return "".join(out)


def wind_grid_points() -> list[tuple[float, float]]:
    """The points a wind field would actually be fetched at, minus the ones on land.

    Roughly a tenth of a degree apart, which over this frame is about thirty locations --
    the size of Open-Meteo request the map's field is budgeted for. Drawing one arrow per
    fetched point rather than a continuous flow keeps the mark honest about the data: it
    is a sample, not a field, and the map should not imply otherwise.
    """
    grid = json.loads((PROMOTED / "bathymetry.json").read_text(encoding="utf-8"))
    z = grid["elevation_m"]
    step = 0.09
    points = []
    lat = grid["lat_top"] - step / 2
    while lat > grid["lat_bottom"]:
        lon = grid["lon_left"] + step / 2
        while lon < grid["lon_right"]:
            r = round((grid["lat_top"] - lat) / grid["step"])
            c = round((lon - grid["lon_left"]) / grid["step"])
            if 0 <= r < grid["rows"] and 0 <= c < grid["cols"] and z[r][c] < 0:
                x = (lon - grid["lon_left"]) / (grid["lon_right"] - grid["lon_left"]) * VIEW_W
                y = (grid["lat_top"] - lat) / (grid["lat_top"] - grid["lat_bottom"]) * VIEW_H
                points.append((x, y))
            lon += step
        lat -= step
    return points


def drift_seconds(speed_kmh: float) -> float:
    """One arrow's travel time across its own spacing. Faster wind, quicker crossing."""
    return round(33.0 / max(speed_kmh, 3.0), 2)


# Every wind glyph is drawn pointing along LOCAL +y, because the rotation puts local +y
# on the direction the wind is travelling and the drift animation runs the same way. The
# first cut had the apex at -y, so the darts flew backwards -- tail first, at the right
# speed, in the right direction. Keep the apex positive.
def _dart(palette: dict, speed_kmh: float) -> str:
    return (f'<path d="M0,9 L3.4,-3.2 L0,-0.9 L-3.4,-3.2 Z" '
            f'fill="{palette["wind"]}"></path>')


def _comet(palette: dict, speed_kmh: float) -> str:
    """A head with a tail whose LENGTH is the speed, so it reads even in a still frame."""
    tail = min(38.0, max(9.0, speed_kmh * 1.15))
    return (f'<path d="M0,7 L2.6,-1.5 L0,{-tail:.1f} L-2.6,-1.5 Z" '
            f'fill="{palette["wind"]}"></path>')


def _barb(palette: dict, speed_kmh: float) -> str:
    """The meteorological wind barb: the staff points INTO the wind and the flags count it.

    Half barb 5 kt, full barb 10 kt, pennant 50 kt, rounded to the nearest 5 -- the
    convention every marine forecast uses. It encodes speed in the glyph rather than in
    the motion, which is the opposite trade from the dart and the comet.
    """
    knots = round(speed_kmh / 1.852 / 5) * 5
    stroke = palette["wind"]
    parts = [f'<line x1="0" y1="0" x2="0" y2="-26" stroke="{stroke}" stroke-width="1.6" '
             'stroke-linecap="round"></line>',
             f'<circle cx="0" cy="4" r="1.9" fill="{stroke}"></circle>']

    y = -26.0
    remaining = knots
    while remaining >= 50:
        parts.append(f'<path d="M0,{y:.1f} L9,{y + 3.4:.1f} L0,{y + 6.8:.1f} Z" '
                     f'fill="{stroke}"></path>')
        remaining -= 50
        y += 8.0
    while remaining >= 10:
        parts.append(f'<line x1="0" y1="{y:.1f}" x2="9" y2="{y + 3.6:.1f}" stroke="{stroke}" '
                     'stroke-width="1.5" stroke-linecap="round"></line>')
        remaining -= 10
        y += 4.6
    if remaining >= 5:
        parts.append(f'<line x1="0" y1="{y:.1f}" x2="4.8" y2="{y + 1.9:.1f}" stroke="{stroke}" '
                     'stroke-width="1.5" stroke-linecap="round"></line>')
    return "".join(parts)


GLYPHS = {"dart": _dart, "comet": _comet, "barb": _barb}


def wind_arrows(palette: dict, prefix: str, *, heading_deg: float = 160.0,
                speed_kmh: float = 12.6, style: str = "dart") -> str:
    """One glyph per grid point, pointing downwind and drifting the way the wind blows."""
    rotate = heading_deg - 180
    glyph = GLYPHS[style](palette, speed_kmh)
    body = [f"<svg {VIEW} {FILL}>",
            f'<defs><g id="{prefix}-wind">{glyph}</g></defs>']
    for index, (x, y) in enumerate(wind_grid_points()):
        delay = -(index % 5) * drift_seconds(speed_kmh) / 5
        body.append(
            f'<g transform="translate({x:.1f},{y:.1f}) rotate({rotate:.0f})">'
            f'<g class="{prefix}-dart" style="animation-delay:{delay:.2f}s">'
            f'<use href="#{prefix}-wind"></use></g></g>'
        )
    body.append("</svg>")
    return "".join(body)


def land_svg(palette: dict) -> str:
    return (
        f"<svg {VIEW} {FILL}>"
        f'<path d="{DATA["land"]}" fill-rule="evenodd" fill="{palette["land"]}" '
        f'stroke="{palette["coast"]}" stroke-width="1.2"></path>'
        f'<circle cx="631" cy="394" r="4.5" fill="{palette["accent"]}"></circle>'
        f'<text x="620" y="381" text-anchor="end" font-family="\'Space Grotesk\',sans-serif" '
        f'font-size="13" font-weight="600" fill="{palette["label"]}">Praia do Norte</text>'
        f'<text x="120" y="470" font-family="\'Space Grotesk\',sans-serif" font-size="10.5" '
        f'letter-spacing="3.4" fill="{palette["faint"]}">NAZARÉ CANYON</text>'
        "</svg>"
    )


def keyframes(prefix: str, *, speed_kmh: float = 12.6) -> str:
    step = 100.0 / len(CRESTS["frames"])
    drift = drift_seconds(speed_kmh)
    return (
        f"@keyframes {prefix}Flick{{0%,{step - 0.01:.3f}%{{opacity:1}}"
        f"{step:.3f}%,100%{{opacity:0}}}}"
        f".{prefix}-crest{{opacity:0;animation:{prefix}Flick {CYCLE_S}s linear infinite}}"
        f"@keyframes {prefix}Dart{{0%{{opacity:0;transform:translateY(-15px)}}"
        "22%{opacity:1}74%{opacity:1}100%{opacity:0;transform:translateY(15px)}}"
        f".{prefix}-dart{{animation:{prefix}Dart {drift}s linear infinite}}"
    )


def map_markup(palette: dict, prefix: str, *, wind_style: str = "dart") -> str:
    return (depth_svg(palette) + crest_svg(palette, prefix)
            + wind_arrows(palette, prefix, style=wind_style) + land_svg(palette))



# One ground, three brand colours. The base is the "Ink" graphite that was chosen; the
# only thing that varies is the colour carrying the wordmark, the nav and the links.
#
# The statuses are NOT the brand colour. A Go Call is a state of the sea, so it gets its
# own colour and keeps it whatever the brand does -- and keeping them separate is what
# stops a page where the loudest thing is a logo.
_BASE = {
    "deep": "#060606", "shelf": "#5e5e5e", "hairline": "rgba(238,235,230,0.2)",
    "land": "#0e0e0e", "coast": "#8e8b86",
    "label": "#ecebe7", "faint": "rgba(228,225,219,0.4)",
    "page": "#0b0b0b", "panel": "#151515", "border": "#252525",
    "text": "#eceae6", "muted": "#9a9791",
    # `swell` is filled in per palette: the brand colour rides the wave fronts. With the
    # statuses pastel and the ground graphite, the wordmark alone gave the main colour
    # almost nothing to do, and three variants that differ only in a logo tint are not a
    # choice. Putting it on the swell also keeps the rule intact -- colour is data.
    "wind": "rgba(206,202,194,0.85)",
    # Pastels, light enough to clear 4.5:1 on this ground at small sizes.
    "go": "#a6dfae", "go_dim": "rgba(166,223,174,0.14)",
    "watch": "#ecdc9a", "watch_dim": "rgba(236,220,154,0.1)",
}

def _variant(name: str, note: str, accent: str, swell: str) -> dict:
    return dict(_BASE, name=name, note=note, accent=accent, swell=swell)


PALETTES = {
    "ice": _variant("Ice", "pale glacier blue", "#8ecfe6", "rgba(150,214,238,0.95)"),
    "violet": _variant("Violet", "cold electric violet", "#b09cf0",
                       "rgba(182,162,246,0.95)"),
    "bone": _variant("Bone", "warm near-neutral, barely a colour", "#e3d6bd",
                     "rgba(232,222,200,0.95)"),
}


def preview() -> None:
    panels, styles = [], []
    for key, palette in PALETTES.items():
        styles.append(keyframes(key))
        panels.append(
            f'<figure style="margin:0"><div style="position:relative;width:560px;height:700px;'
            f'overflow:hidden;background:{palette["deep"]}">{map_markup(palette, key)}</div>'
            f'<figcaption style="font:12px system-ui;color:#bbb;padding-top:8px">'
            f'{palette["name"]} &mdash; {palette["note"]}</figcaption></figure>'
        )

    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Space+Grotesk:wght@400;500;600&display=swap"><style>'
        'body{margin:0;background:#161616;padding:24px;display:flex;gap:24px}'
        + "".join(styles) +
        '</style></head><body>' + "".join(panels) + '</body></html>'
    )
    (HERE / "preview.html").write_text(html, encoding="utf-8")
    print(f"wrote {HERE / 'preview.html'}  ({len(html) // 1024} kB)")


if __name__ == "__main__":
    preview()
