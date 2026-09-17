# v2 map prototype — the data pipeline behind the canyon

Throwaway by intention, but **not cheap to reproduce**: `bathymetry.json` cost 129 requests
against a free, rate-limited API at one request a second. Re-run the fetch only if the frame
changes.

Nothing here is wired into the application. It exists because the v2 map's design could not be
settled without real depth data, and the scripts that produced that data turned out to be the
same ones a real implementation would use. Read
`docs/superpowers/specs/2026-09-17-nazarenow-v2-design.md` for what was decided on the strength
of them.

## Order of operations

```
fetch_bathymetry.py   ->  bathymetry.json     12,826 GEBCO 2020 soundings, 15 arc-seconds
contours.py           ->  contours.json       marching squares + Douglas-Peucker, ~20 kB of paths
refraction.py         ->  crests.json         16 phases of a refracting wave front
build_map.py          ->  preview.html        palette comparison, and the shared map markup
build_artboards.py    ->  artboards/*.dc.html the design-canvas artboards
```

`build_artboards.py` imports `build_map.py`, which imports both JSON files. `refraction.py`
imports `contours.py` for the polyline joiner and the simplifier. Run them from this directory.

## The two files worth keeping

- **`bathymetry.json`** — the frame that shipped: 39.40–39.82°N, 9.04–9.52°W, 0.004° steps,
  106 × 121, deepest point 1,546 m. `bathymetry-wide.json` is the first, coarser sample over a
  larger box; it is what proved where the canyon actually is, and is kept for that reason.
- **`contours.json`** — the traced result. Regenerating it from the grid takes under a second,
  so this is a convenience rather than a necessity.

## Defects already found and fixed here, so they are not re-found later

1. **Band fills stacked the wrong way.** Each level's path fills everything *deeper* than it, so
   the bands must be painted shallow-to-deep. Painted deep-to-shallow, the shallowest level
   floods the entire ocean with the shelf tone and the canyon disappears completely.
2. **Closed contours need `fill-rule="evenodd"`.** A closed loop inside a band is a rise — a
   seamount — not a hole. Filled with the default non-zero rule it paints as a black blob in
   open water. Two of those appeared and were mistaken for land before the cause was found.
3. **Open coastline fragments must be closed around the frame edge, not end-to-start.** Closing
   a coast segment directly from its last point to its first draws a teardrop out at sea.
4. **Wind glyphs point along local `+y`.** The rotation puts local `+y` on the direction of
   travel and the drift animation runs the same way, so a glyph drawn with its apex at `−y`
   flies tail-first — at the correct speed, in the correct direction, which is what makes it
   hard to spot.

## What is honest about it, and what is not

The bathymetry, the coastline, the Berlengas, the seamounts and the Lagoa de Óbidos are all
data. The wave fronts' *shape* is computed from that data by a refraction model that is named
wherever it is shown. Their *spacing* is exaggerated: a 13.75 s swell has a 295 m wavelength,
which over this frame is 160 crests and a moiré pattern.

The model is refraction only — `c = min(gT/2π, √(gd))` — and ignores diffraction, reflection,
currents, non-linearity, and the fact that a real swell is a spread of periods and directions
rather than one. It is not a spectral wave model and must never be described as one.
