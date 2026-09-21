/**
 * The canyon, drawn from soundings (#121).
 *
 * **Nothing here is illustrated.** The shape comes from 12,826 GEBCO soundings traced into
 * contours by `scripts/map/contours.py` and committed as `map-geometry.json`. The first attempt
 * at this map drew the canyon by hand and was rejected outright: the canyon is the one shape on
 * earth that makes Nazaré what it is, and a drawing of it would make the whole instrument a
 * picture of an opinion. The Berlengas, the two seamounts and the Lagoa de Óbidos are on this
 * map because they are in the soundings, not because anyone drew them.
 *
 * **Greyscale only.** On this map colour means live data — swell, wind, a call — so the base it
 * is read against carries none. Every tone is a token; `ink.test.ts` fails on a colour named
 * outside `tokens.css`, which is why the bands are classes rather than a fill computed here.
 *
 * Inline SVG, no map library and no charting library. The frame is one fixed view of one fixed
 * place and nothing reprojects anything, so there is nothing for a library to do.
 */

import { Crests } from './Crests';
import { Wind } from './Wind';
import geometry from './map-geometry.json';
import type { ConditionsGrid } from './api';
import type { Swell } from './refraction';

/**
 * The bands and the hairlines, exactly as the build step emitted them.
 *
 * **Nothing about the geometry is decided here.** The levels, their order and the closure of
 * every open contour against the frame are `scripts/map/contours.py`'s, because they are
 * questions about the soundings rather than about the page. This file had a `closeWest` of its
 * own and it was wrong for two of the eight bands — the same path-closing rule living in two
 * languages, which is one more place than it can be right in.
 */
const BANDS: { level: number; d: string }[] = geometry.bands;
const LEVELS: Record<string, string[]> = geometry.levels;

export function Bathymetry({ swell, grid }: { swell: Swell | null; grid: ConditionsGrid | null }) {
  return (
    <svg
      className="bathymetry"
      viewBox={geometry.viewBox}
      /* **`meet`, so the whole frame is drawn, and `YMin`, so the space it leaves is one band
         below the map rather than two around it.** This was `xMidYMid slice` and the crop took
         two of the five wind columns with it. The measurement and the argument are in
         `docs/adr/0015-the-whole-frame-is-drawn.md`; they are not repeated here, because a
         figure copied to a fourth place is a figure that can go stale in three. */
      preserveAspectRatio="xMidYMin meet"
      role="img"
      aria-label="The sea floor off Praia do Norte, drawn from soundings: the Nazaré Canyon reaching the coast, the shelf either side of it, and the coastline"
    >
      {/* The deepest tone, behind everything. Every band is painted on top of it. */}
      <rect className="bathymetry-deep" x="0" y="0" width="100%" height="100%" />

      {BANDS.map((band, index) => (
        <path
          key={`band-${band.level}`}
          className={`bathymetry-band bathymetry-band-${index}`}
          d={band.d}
          /* **Even-odd, not the default non-zero, and the second defect the prototype found.**
             A closed loop inside a band is a rise — a seamount, or the shoulder between the
             canyon and the shelf — not a hole in the sea floor. Under the non-zero rule it
             paints as a dark blob in open water; two of those appeared in the prototype and
             were mistaken for land before the cause was found. */
          fillRule="evenodd"
        />
      ))}

      {BANDS.map((band) => (
        <path
          key={`hairline-${band.level}`}
          className="bathymetry-hairline"
          d={(LEVELS[String(band.level)] ?? []).join('')}
        />
      ))}

      {/* The swell, over the water and under the land (#122). Solved in the page against the
          live period and direction — see `Crests.tsx` and ADR 0016. Null until the conditions
          arrive, and then nothing is drawn: a default sea would be a picture of a swell nobody
          reported. */}
      <Crests swell={swell} />

      {/* The wind over the water and under the land (#123). One dart per point the endpoint
          actually returned — never an interpolated field — and nothing at all when there is
          no grid, because a map with no darts cannot be told from a map of a flat calm. */}
      <Wind grid={grid} />

      {/* Land last, over the water it borders.

          The third defect lives in how this path was built rather than in how it is drawn: an
          open coast fragment closed straight from its last point back to its first draws a
          teardrop out at sea, so `contours.py` closes it around the eastern edge instead. The
          even-odd rule is what lets the Lagoa de Óbidos be a real lagoon punched back out of
          the land rather than a painted-over inlet. */}
      <path className="bathymetry-land" d={geometry.land} fillRule="evenodd" />
    </svg>
  );
}
