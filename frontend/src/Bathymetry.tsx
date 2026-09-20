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

import geometry from './map-geometry.json';

/**
 * The levels that become filled bands, shallow to deep.
 *
 * Fewer than were traced, and deliberately uneven: the steps that matter are the ones the
 * canyon walls cross, and an even ramp spends its contrast on open shelf where nothing is
 * happening.
 *
 * **The order is load-bearing and the first defect the prototype found.** Each level's path
 * fills everything *deeper* than it, so painting shallow-to-deep leaves the canyon floor as
 * the last and darkest thing drawn. Reversed, the shallowest level floods the entire ocean with the
 * shelf tone and the canyon disappears completely — which looks like a palette problem and is
 * not.
 */
const BANDS = [-20, -75, -155, -280, -460, -700, -1000, -1400] as const;

const LEVELS: Record<string, string[]> = geometry.levels;

/** Far enough outside the frame that the closing edge is never visible inside it. */
const WEST = -60;

/**
 * Close an open contour around the western edge of the frame.
 *
 * A band is "everything deeper than this level". A contour that leaves the frame has to be
 * closed against the edge it leaves through, or the fill takes a short cut across open water.
 * Closed contours already end in `Z` and are left alone.
 */
function closeWest(path: string): string {
  if (path.endsWith('Z')) return path;
  const points = path.slice(1).replace(/L/g, ' ').split(/\s+/).filter(Boolean);
  const first = points[0]!.split(',');
  const last = points[points.length - 1]!.split(',');
  return `${path}L${WEST},${last[1]}L${WEST},${first[1]}Z`;
}

function bandPath(level: number): string {
  return (LEVELS[String(level)] ?? []).map(closeWest).join('');
}

function hairlinePath(level: number): string {
  return (LEVELS[String(level)] ?? []).join('');
}

export function Bathymetry() {
  return (
    <svg
      className="bathymetry"
      viewBox={geometry.viewBox}
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label="The sea floor off Praia do Norte, drawn from soundings: the Nazaré Canyon reaching the coast, the shelf either side of it, and the coastline"
    >
      {/* The deepest tone, behind everything. Every band is painted on top of it. */}
      <rect className="bathymetry-deep" x="0" y="0" width="100%" height="100%" />

      {BANDS.map((level, index) => (
        <path
          key={`band-${level}`}
          className={`bathymetry-band bathymetry-band-${index}`}
          d={bandPath(level)}
          /* **Even-odd, not the default non-zero, and the second defect the prototype found.**
             A closed loop inside a band is a rise — a seamount, or the shoulder between the
             canyon and the shelf — not a hole in the sea floor. Under the non-zero rule it
             paints as a dark blob in open water; two of those appeared in the prototype and
             were mistaken for land before the cause was found. */
          fillRule="evenodd"
        />
      ))}

      {BANDS.map((level) => (
        <path key={`hairline-${level}`} className="bathymetry-hairline" d={hairlinePath(level)} />
      ))}

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
