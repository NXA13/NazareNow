/**
 * The refraction solve, tested as physics rather than as output.
 *
 * This runs in the browser (ADR 0016) against the live swell, so there is no precomputed
 * field to compare against and no bin to look up. What can be asserted instead is the
 * behaviour the model is *for*: a flat sea bends nothing, and shallow water lags the front.
 * Both have answers that are known before the code runs, which is the point — a snapshot of
 * whatever the solve happens to emit would pass against a solve that had stopped doing
 * physics entirely.
 *
 * `refraction.parity.test.ts` pins the whole pipeline against the committed output of
 * `prototypes/v2-map/refraction.py`, which stays the reference implementation.
 */

import { describe, expect, it } from 'vitest';

import { CREST_SPACING, crestFrames, type DepthGrid } from './refraction';

/** A rectangle of sea at one depth, with the frame's real proportions. */
function flatSea(depthMetres: number, rows = 40, cols = 40): DepthGrid {
  return {
    rows,
    cols,
    elevationMetres: new Array(rows * cols).fill(-depthMetres),
    viewWidth: 400,
    viewHeight: 400,
    metresPerUnit: 60,
  };
}

const SWELL = { periodSeconds: 13.75, fromDirectionDeg: 0 };

describe('a flat sea bends nothing', () => {
  // Due south means the front travels along the grid's own axis, so the eight-neighbour
  // search has a straight path available and adds no staircase error. Any bend in the
  // result is therefore the model, not the discretisation.
  const frames = crestFrames(flatSea(2000), SWELL);
  const crests = frames.flat();

  it('draws crests at all', () => {
    expect(crests.length).toBeGreaterThan(0);
  });

  it('holds every crest flat across the whole frame', () => {
    // Without this line the loop below passes against no crests at all, which is how a
    // solve that had stopped emitting anything would read as correct.
    expect(crests.length).toBeGreaterThan(0);
    for (const crest of crests) {
      const ys = crest.points.map(([, y]) => y);
      expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(0.5);
    }
  });

  it('runs each crest the full width, because nothing stops it', () => {
    const widest = Math.max(
      ...crests.map((c) => {
        const xs = c.points.map(([x]) => x);
        return Math.max(...xs) - Math.min(...xs);
      }),
    );
    expect(widest).toBeGreaterThan(390);
  });
});

describe('the front moves at the deep-water celerity', () => {
  // The bar test below only shows that one side LAGS the other, and "the shallow side is
  // slow" and "the deep side is extra fast" both produce a lag. Inverting the celerity law
  // to `max(c_deep, sqrt(gd))` passed every other test in this file. This one pins the
  // absolute scale: crests one interval apart in TIME must land one CREST_SPACING apart in
  // SPACE, and they only do that if the front is moving at the speed the interval assumes.
  it('lands consecutive crests exactly one spacing apart over a flat deep sea', () => {
    const crests = crestFrames(flatSea(2000), SWELL)[0]!;
    expect(crests.length).toBeGreaterThan(2);
    const ys = crests.map((c) => c.points[0]![1]).sort((a, b) => a - b);
    const gaps = ys.slice(1).map((y, i) => y - ys[i]!);
    for (const gap of gaps) {
      expect(gap).toBeCloseTo(CREST_SPACING, 1);
    }
  });
});

describe('shallow water lags the front', () => {
  /** The same sea with a shallow bar down the left half, which must slow that side. */
  function barredSea(): DepthGrid {
    const grid = flatSea(2000);
    for (let r = 0; r < grid.rows; r++) {
      for (let c = 0; c < grid.cols / 2; c++) {
        (grid.elevationMetres as number[])[r * grid.cols + c] = -8;
      }
    }
    return grid;
  }

  it('leaves the crest behind over the bar and ahead over the deep half', () => {
    const crests = crestFrames(barredSea(), SWELL).flat();
    // Travelling south, y grows with time, so the slow side is the side with the SMALLER y.
    const bent = crests.filter((c) => {
      const xs = c.points.map(([x]) => x);
      return Math.min(...xs) < 100 && Math.max(...xs) > 300;
    });
    expect(bent.length).toBeGreaterThan(0);
    for (const crest of bent) {
      const overBar = crest.points.filter(([x]) => x < 150).map(([, y]) => y);
      const overDeep = crest.points.filter(([x]) => x > 250).map(([, y]) => y);
      const meanBar = overBar.reduce((s, y) => s + y, 0) / overBar.length;
      const meanDeep = overDeep.reduce((s, y) => s + y, 0) / overDeep.length;
      expect(meanBar).toBeLessThan(meanDeep);
    }
  });

  it('does not bend a flat sea, which is what makes the bend above mean something', () => {
    const crests = crestFrames(flatSea(2000), SWELL).flat();
    expect(crests.length).toBeGreaterThan(0);
    const spans = crests.map((c) => {
      const ys = c.points.map(([, y]) => y);
      return Math.max(...ys) - Math.min(...ys);
    });
    expect(Math.max(...spans)).toBeLessThan(0.5);
  });
});
