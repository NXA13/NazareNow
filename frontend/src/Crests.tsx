/**
 * The swell, bending over the canyon (#122).
 *
 * The fronts are isochrones of a refraction solve run here, in the page, against the live
 * swell period and direction — not a precomputed field looked up from a bin. ADR 0016 has the
 * argument and the measurements; the short version is that the direction axis needed fine bins
 * and fine bins came to 302 kB, while the solve costs 2.7 ms.
 *
 * **Two things must be said wherever this map is explained, and `MapSlot` says them**: the
 * crest *shape* is computed and the crest *spacing* is exaggerated, and the model is refraction
 * alone. This file draws them; it does not get to decide whether they are explained.
 *
 * Each front is drawn twice — dim out in deep water, bright inside the shoaling zone — because
 * the shoaling zone is exactly where the bending begins, and showing where the bending starts
 * is the whole reason this is on the page.
 */

import { useEffect, useMemo, useState } from 'react';

import packed from './depth-grid.json';
import { decodeDepthGrid } from './depth-grid';
import { crestPaths, type DepthGrid, type Swell } from './refraction';

/** Decoded once for the life of the page: the soundings do not change. */
const GRID: DepthGrid = {
  rows: packed.rows,
  cols: packed.cols,
  elevationMetres: decodeDepthGrid(packed),
  viewWidth: packed.viewWidth,
  viewHeight: packed.viewHeight,
  metresPerUnit: packed.metresPerUnit,
};

const FRAME_COUNT = 16;
/** One loop of the animation is FRAME_COUNT × this, so about 1.8 s per crest interval. */
const FRAME_MS = 110;

/**
 * Which phase to draw, advancing unless the reader has asked for less motion.
 *
 * A still frame of this map is still honest — the *shape* is the informative part and it does
 * not depend on the phase — so `prefers-reduced-motion` simply stops it rather than needing a
 * different picture.
 */
function useCrestPhase(frameCount: number): number {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    if (frameCount < 2) return;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    if (reduced) return;
    const timer = window.setInterval(() => {
      setFrame((current) => (current + 1) % frameCount);
    }, FRAME_MS);
    return () => window.clearInterval(timer);
  }, [frameCount]);

  return frame % Math.max(1, frameCount);
}

export function Crests({ swell }: { swell: Swell | null }) {
  // Keyed on the two numbers rather than the object, so a re-render with an equal-but-new
  // conditions object does not re-run a 50 ms solve.
  const period = swell?.periodSeconds ?? null;
  const direction = swell?.fromDirectionDeg ?? null;
  const frames = useMemo(
    () =>
      period === null || direction === null
        ? []
        : crestPaths(GRID, { periodSeconds: period, fromDirectionDeg: direction }, FRAME_COUNT),
    [period, direction],
  );

  const phase = useCrestPhase(frames.length);
  const frame = frames[phase];
  if (!frame) return null;

  return (
    <g className="bathymetry-crests" aria-hidden="true">
      {frame.deep.map((d, index) => (
        <path key={`deep-${index}`} className="bathymetry-crest bathymetry-crest-deep" d={d} />
      ))}
      {frame.shoaling.map((d, index) => (
        <path
          key={`shoaling-${index}`}
          className="bathymetry-crest bathymetry-crest-shoaling"
          d={d}
        />
      ))}
    </g>
  );
}
