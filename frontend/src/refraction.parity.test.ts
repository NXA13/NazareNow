/**
 * The port, pinned against the reference implementation.
 *
 * `prototypes/v2-map/refraction.py` is where this model was worked out and it stays the
 * reference (ADR 0016). `refraction.ts` is a port of it, and a port is exactly the kind of
 * code that drifts silently: every test in `refraction.test.ts` would still pass against a
 * solve that had picked up a subtly different neighbour cost or a different seeding rule,
 * because those tests assert the physics rather than the numbers.
 *
 * So this runs the real sea floor through both and compares them vertex by vertex.
 *
 * **The one licensed difference is the last printed decimal.** Python's `%.1f` rounds halves
 * to even and JavaScript's `toFixed` rounds them away from zero, so a coordinate landing
 * exactly on a half can differ by 0.1 view units — 0.08 px on a 1440×900 desktop. Nothing
 * else may differ, and the assertion below is tight enough that a genuine change in the
 * physics cannot hide inside it.
 *
 * If this fails, do not update the fixture. Regenerate it with `python refraction.py` only
 * after deciding that the *model* should change, and say so in the commit.
 */

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import packed from './depth-grid.json';
import { decodeDepthGrid } from './depth-grid';
import { crestFrames, type DepthGrid } from './refraction';

// Resolved from the working directory, not from `import.meta.url`, which under Vite is a
// module-graph URL rather than a file path. Vitest is run from `frontend/` in this repo — from
// the root it picks up a different vitest with no config and still reports passes — so the
// fixture is one level up. A missing fixture must shout rather than silently skip.
const FIXTURE = resolve(process.cwd(), '../prototypes/v2-map/crests.json');
if (!existsSync(FIXTURE)) {
  throw new Error(
    `Reference crests not found at ${FIXTURE}. Run vitest from frontend/, and regenerate with ` +
      '`python prototypes/v2-map/refraction.py` if the file is genuinely missing.',
  );
}
const reference = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as {
  period_s: number;
  from_direction_deg: number;
  frames: string[][];
};

const grid: DepthGrid = {
  rows: packed.rows,
  cols: packed.cols,
  elevationMetres: decodeDepthGrid(packed),
  viewWidth: packed.viewWidth,
  viewHeight: packed.viewHeight,
  metresPerUnit: packed.metresPerUnit,
};

/** The half-even / half-away rounding difference, and nothing more than it. */
const ROUNDING_SLACK = 0.1 + 1e-9;

function vertices(path: string): [number, number][] {
  return path
    .slice(1)
    .split('L')
    .map((pair) => {
      const [x, y] = pair.split(',').map(Number);
      return [x, y] as [number, number];
    });
}

describe('the browser solve matches refraction.py', () => {
  const mine = crestFrames(grid, {
    periodSeconds: reference.period_s,
    fromDirectionDeg: reference.from_direction_deg,
  });

  it('is comparing something, on the real sea floor', () => {
    // Without this the per-frame loops below would pass against an empty fixture or an
    // empty solve, which is how a port that had stopped working would read as identical.
    expect(reference.frames).toHaveLength(16);
    expect(reference.frames.flat().length).toBeGreaterThan(200);
    expect(grid.rows * grid.cols).toBe(12826);
  });

  it('draws the same number of frames', () => {
    expect(mine).toHaveLength(reference.frames.length);
  });

  it('draws the same crests, frame by frame', () => {
    const counts = mine.map((frame) => frame.length);
    expect(counts).toEqual(reference.frames.map((frame) => frame.length));
  });

  it('puts every vertex within the rounding slack, and no further', () => {
    let compared = 0;
    let worst = 0;
    for (let f = 0; f < reference.frames.length; f++) {
      for (let p = 0; p < reference.frames[f]!.length; p++) {
        const theirs = vertices(reference.frames[f]![p]!);
        const ours = mine[f]![p]!.points;
        expect(ours).toHaveLength(theirs.length);
        for (let v = 0; v < theirs.length; v++) {
          worst = Math.max(
            worst,
            Math.abs(ours[v]![0] - theirs[v]![0]),
            Math.abs(ours[v]![1] - theirs[v]![1]),
          );
          compared++;
        }
      }
    }
    expect(compared).toBeGreaterThan(2000);
    expect(worst).toBeLessThanOrEqual(ROUNDING_SLACK);
  });
});
