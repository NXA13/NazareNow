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

import {
  celerity,
  CREST_SPACING,
  crestFrames,
  crestPaths,
  shoalingDepth,
  type DepthGrid,
} from './refraction';

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

describe('crests are split where the swell starts to feel the bottom', () => {
  // The map draws each front twice: dim out in deep water, bright where the front has begun
  // to bend. The split is the depth at which it has slowed by 5%, so it MOVES with the period
  // rather than being a fixed contour — 81.75 m at 13.75 s, 15.57 m at 6 s.
  const shallowShelfEast = (): DepthGrid => {
    const grid = flatSea(2000, 40, 40);
    const elevation = grid.elevationMetres as number[];
    for (let r = 0; r < grid.rows; r++) {
      for (let c = 20; c < grid.cols; c++) elevation[r * grid.cols + c] = -20;
    }
    return grid;
  };

  it('puts the bright crests over the shallow half and the dim ones over the deep half', () => {
    const [frame] = crestPaths(shallowShelfEast(), SWELL);
    expect(frame!.shoaling.length).toBeGreaterThan(0);
    expect(frame!.deep.length).toBeGreaterThan(0);

    const meanX = (paths: string[]) => {
      const xs = paths.flatMap((d) =>
        d
          .slice(1)
          .split('L')
          .map((pair) => Number(pair.split(',')[0])),
      );
      return xs.reduce((s, x) => s + x, 0) / xs.length;
    };
    // The shelf is the eastern half of this sea, so the bright crests must sit east of the
    // dim ones. A split that had stopped depending on depth would put them on top of
    // each other and this comparison would fail.
    expect(meanX(frame!.shoaling)).toBeGreaterThan(meanX(frame!.deep) + 100);
  });

  it('moves the boundary with the period, because a longer wave feels the bottom sooner', () => {
    // At 2000 m nothing has slowed at any period, so the whole frame must be dim. A boundary
    // that had stopped depending on depth would light this up.
    const [deepOnly] = crestPaths(flatSea(2000), SWELL);
    expect(deepOnly!.shoaling).toHaveLength(0);
    expect(deepOnly!.deep.length).toBeGreaterThan(0);

    const long = shoalingDepth(16);
    const short = shoalingDepth(8);
    expect(long).toBeGreaterThan(short * 1.5);

    // A sea between the two boundaries is bright for the long swell and dim for the short
    // one, in the same water — which is the whole claim the split makes.
    const between = (long + short) / 2;
    const [longPeriod] = crestPaths(flatSea(between), { periodSeconds: 16, fromDirectionDeg: 0 });
    const [shortPeriod] = crestPaths(flatSea(between), { periodSeconds: 8, fromDirectionDeg: 0 });
    expect(longPeriod!.shoaling.length).toBeGreaterThan(0);
    expect(shortPeriod!.shoaling).toHaveLength(0);
  });
});

describe('the wave slows over the shelf, not only at the beach', () => {
  /**
   * This is the test that the first version of this model could not pass, and the reason the
   * map drew near-straight lines while every other test here was green.
   *
   * The model was `c = min(c_deep, sqrt(g*d))`, which is flat — *exactly* deep-water celerity —
   * for every depth below `c_deep²/g`, which at 13.75 s is 47 m. The Nazaré shelf is 100–200 m
   * and the canyon is over 1000 m, so under that law the shelf and the canyon ran at identical
   * speed, and the contrast between them is the whole reason the front bends. Nothing could
   * refract until the wave was inside the 47 m contour, which hugs the shore.
   *
   * The real dispersion relation, ω² = gk·tanh(kd), has the wave at 97.5% of deep-water speed
   * in 100 m and 89% in 60 m. Small differences, compounded over 40 km of shelf, are the bend.
   */
  const T = 13.75;

  it('runs slower over a 100 m shelf than in open ocean', () => {
    const open = celerity(4000, T);
    const shelf = celerity(100, T);
    expect(shelf).toBeLessThan(open * 0.99);
    expect(shelf).toBeGreaterThan(open * 0.95);
  });

  it('slows monotonically as the water shallows, with no flat step', () => {
    // A flat step is exactly what the old law had, and what made the shelf invisible.
    const depths = [4000, 500, 300, 200, 150, 100, 80, 60, 40, 20, 10, 5];
    const speeds = depths.map((d) => celerity(d, T));
    for (let i = 1; i < speeds.length; i++) {
      expect(speeds[i]!, `${depths[i]} m is not slower than ${depths[i - 1]} m`).toBeLessThan(
        speeds[i - 1]!,
      );
    }
  });

  it('matches the deep-water and shallow-water limits it sits between', () => {
    // Expected values from the two closed forms, not from this function, so agreeing with
    // itself is not enough to pass.
    expect(celerity(10000, T)).toBeCloseTo((9.81 * T) / (2 * Math.PI), 2);
    // The shallow-water form is a LIMIT, approached from below as kd goes to zero, not a
    // value this should equal: at 3 m and 13.75 s, kd is 0.25 and the true celerity is about
    // 1% under sqrt(gd). Asserting equality here would be asserting the approximation.
    // 3 m and not less because `celerity` floors depth at 2 m on purpose, so the shore cells
    // cost time rather than stalling the whole front on one pixel of surf zone.
    const ratio = celerity(3, T) / Math.sqrt(9.81 * 3);
    expect(ratio).toBeLessThan(1);
    expect(ratio).toBeGreaterThan(0.98);
  });
});
