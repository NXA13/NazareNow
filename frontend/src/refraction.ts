/**
 * Where the swell bends, solved here rather than fetched.
 *
 * A swell arriving at Nazaré does not stay straight. In water shallower than about half its
 * wavelength it slows, and a front travelling partly over the shelf and partly over the canyon
 * bends towards the slow side. The canyon, being deep, stays fast — so the fronts either side
 * of it lag, the front wraps around the canyon head, and the energy that should have spread
 * along ten kilometres of beach arrives at one peak. That convergence *is* the wave.
 *
 * The model is the schoolbook one, and is named as such wherever it is shown:
 *
 *     celerity  c = min(c_deep, sqrt(g * depth))      c_deep = g * T / 2*pi
 *
 * Travel time from the open ocean is a shortest-path problem over the depth grid — Dijkstra
 * with eight neighbours, cost = distance / celerity — seeded with a straight plane wave on the
 * upwind edges. Crests are isochrones of that field, so they bend, stall and wrap for exactly
 * the reason real ones do. Animating means stepping the phase.
 *
 * **What this is NOT: a spectral wave model.** It ignores diffraction, reflection, currents,
 * non-linearity and the fact that a real swell is a spread of periods and directions rather
 * than one. It is a picture of refraction alone, at one period, and the caption says so.
 *
 * **Why it runs here and not at build time (ADR 0016).** The plan was to precompute crest
 * fields for binned period and direction. Measured, the direction axis passes its bin width
 * through to the screen almost undamped — 10° in, 9.35° of front rotation out — so the bins
 * could not be coarse, and fine ones came to 302 kB against a 130 kB site. The solve itself
 * costs 2.7 ms. `prototypes/v2-map/refraction.py` stays the reference implementation and
 * `refraction.parity.test.ts` pins this against its committed output.
 */

const G = 9.81;

/** How far apart the drawn crests are, in view units. See the note on exaggeration below. */
export const CREST_SPACING = 38.0;

/**
 * The shore cells get a 2 m floor so they cost time rather than infinity; without it the
 * whole front stalls on one pixel of surf zone.
 */
const MIN_DEPTH_M = 2.0;

export interface DepthGrid {
  rows: number;
  cols: number;
  /** Metres, negative below sea level, row-major. */
  elevationMetres: number[] | Int16Array;
  viewWidth: number;
  viewHeight: number;
  /** Metres per view unit. */
  metresPerUnit: number;
}

export interface Swell {
  periodSeconds: number;
  /** Degrees the swell arrives FROM, as the conditions report it. */
  fromDirectionDeg: number;
}

export interface Crest {
  points: [number, number][];
}

/** Deep-water celerity, which is also the ceiling on celerity anywhere. */
export function deepCelerity(periodSeconds: number): number {
  return (G * periodSeconds) / (2 * Math.PI);
}

/** Depth at which the swell starts to feel the bottom: half the deep-water wavelength. */
export function shoalingDepth(periodSeconds: number): number {
  return (G * periodSeconds * periodSeconds) / (2 * Math.PI) / 2;
}

/** A binary heap of (time, cell), because the solve is the hot path and an array sort is not. */
class Frontier {
  private time: Float64Array;
  private cell: Int32Array;
  size = 0;

  constructor(capacity: number) {
    this.time = new Float64Array(capacity);
    this.cell = new Int32Array(capacity);
  }

  private swap(a: number, b: number) {
    const t = this.time[a]!;
    this.time[a] = this.time[b]!;
    this.time[b] = t;
    const c = this.cell[a]!;
    this.cell[a] = this.cell[b]!;
    this.cell[b] = c;
  }

  push(time: number, cell: number) {
    if (this.size === this.time.length) {
      const bigger = new Float64Array(this.size * 2);
      bigger.set(this.time);
      this.time = bigger;
      const biggerCells = new Int32Array(this.size * 2);
      biggerCells.set(this.cell);
      this.cell = biggerCells;
    }
    let i = this.size++;
    this.time[i] = time;
    this.cell[i] = cell;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.time[parent]! <= this.time[i]!) break;
      this.swap(parent, i);
      i = parent;
    }
  }

  pop(): [number, number] {
    const time = this.time[0]!;
    const cell = this.cell[0]!;
    this.size--;
    if (this.size > 0) {
      this.time[0] = this.time[this.size]!;
      this.cell[0] = this.cell[this.size]!;
      let i = 0;
      for (;;) {
        const left = 2 * i + 1;
        const right = left + 1;
        let smallest = i;
        if (left < this.size && this.time[left]! < this.time[smallest]!) smallest = left;
        if (right < this.size && this.time[right]! < this.time[smallest]!) smallest = right;
        if (smallest === i) break;
        this.swap(smallest, i);
        i = smallest;
      }
    }
    return [time, cell];
  }
}

/**
 * Seconds since the plane wave crossed the upwind corner of the frame.
 *
 * `Infinity` on land and anywhere the front cannot reach, which is what stops an isochrone
 * being drawn across a headland.
 */
export function travelTime(grid: DepthGrid, swell: Swell): Float64Array {
  const { rows, cols, elevationMetres: elevation } = grid;
  const count = rows * cols;
  const deep = deepCelerity(swell.periodSeconds);

  const celerity = new Float64Array(count);
  for (let i = 0; i < count; i++) {
    const elevationHere = elevation[i]!;
    celerity[i] =
      elevationHere >= 0
        ? -1
        : Math.min(deep, Math.sqrt(G * Math.max(-elevationHere, MIN_DEPTH_M)));
  }

  // Direction of travel, in view coordinates: x east, y south. The conditions report the
  // direction the swell comes FROM, so travel is the reciprocal.
  const heading = ((swell.fromDirectionDeg + 180) % 360) * (Math.PI / 180);
  const dx = Math.sin(heading);
  const dy = -Math.cos(heading);

  const unitsPerCol = grid.viewWidth / (cols - 1);
  const unitsPerRow = grid.viewHeight / (rows - 1);

  const best = new Float64Array(count).fill(Infinity);
  const frontier = new Frontier(count);

  // Seed every cell on the two upwind edges with the time a straight front would reach it,
  // so the front enters the frame flat and only the sea bends it.
  let earliest = Infinity;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const onEdge =
        (r === 0 && dy > 0) ||
        (r === rows - 1 && dy < 0) ||
        (c === 0 && dx > 0) ||
        (c === cols - 1 && dx < 0);
      const i = r * cols + c;
      if (!onEdge || celerity[i]! < 0) continue;
      const time = ((c * unitsPerCol * dx + r * unitsPerRow * dy) * grid.metresPerUnit) / deep;
      if (time < best[i]!) {
        best[i] = time;
        if (time < earliest) earliest = time;
      }
    }
  }
  // Normalise so the earliest seed is zero; the absolute datum is meaningless.
  for (let i = 0; i < count; i++) {
    if (best[i] !== Infinity) {
      best[i]! -= earliest;
      frontier.push(best[i]!, i);
    }
  }

  const stepRow = [-1, 1, 0, 0, -1, -1, 1, 1];
  const stepCol = [0, 0, -1, 1, -1, 1, -1, 1];
  while (frontier.size > 0) {
    const [time, i] = frontier.pop();
    if (time > best[i]!) continue;
    const r = (i / cols) | 0;
    const c = i - r * cols;
    const here = celerity[i]!;
    for (let k = 0; k < 8; k++) {
      const nr = r + stepRow[k]!;
      const nc = c + stepCol[k]!;
      if (nr < 0 || nr >= rows || nc < 0 || nc >= cols) continue;
      const j = nr * cols + nc;
      const there = celerity[j]!;
      if (there < 0) continue;
      const step =
        Math.hypot(stepRow[k]! * unitsPerRow, stepCol[k]! * unitsPerCol) * grid.metresPerUnit;
      // Average the two speeds: a front crossing a steep canyon wall spends half the step in
      // each, and using only the destination's speed makes the wall itself a discontinuity
      // the isochrones then trace as a false crest.
      const candidate = time + step / ((here + there) / 2);
      if (candidate < best[j]!) {
        best[j] = candidate;
        frontier.push(candidate, j);
      }
    }
  }
  return best;
}

type Point = [number, number];

function chainLength(points: Point[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    total += Math.hypot(points[i]![0] - points[i - 1]![0], points[i]![1] - points[i - 1]![1]);
  }
  return total;
}

/** Marching squares over the travel-time field: one crest at one instant, as loose segments. */
function isochroneSegments(grid: DepthGrid, field: Float64Array, level: number): [Point, Point][] {
  const { rows, cols } = grid;
  const segments: [Point, Point][] = [];
  const toView = (col: number, row: number): Point => [
    (col / (cols - 1)) * grid.viewWidth,
    (row / (rows - 1)) * grid.viewHeight,
  ];
  const interp = (
    ca: number,
    ra: number,
    va: number,
    cb: number,
    rb: number,
    vb: number,
  ): Point => {
    const t = vb === va ? 0.5 : (level - va) / (vb - va);
    return toView(ca + (cb - ca) * t, ra + (rb - ra) * t);
  };

  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      const tl = field[r * cols + c]!;
      const tr = field[r * cols + c + 1]!;
      const bl = field[(r + 1) * cols + c]!;
      const br = field[(r + 1) * cols + c + 1]!;
      if (tl === Infinity || tr === Infinity || bl === Infinity || br === Infinity) continue;
      const index =
        (tl > level ? 1 : 0) | (tr > level ? 2 : 0) | (br > level ? 4 : 0) | (bl > level ? 8 : 0);
      if (index === 0 || index === 15) continue;
      const top = interp(c, r, tl, c + 1, r, tr);
      const right = interp(c + 1, r, tr, c + 1, r + 1, br);
      const bottom = interp(c, r + 1, bl, c + 1, r + 1, br);
      const left = interp(c, r, tl, c, r + 1, bl);
      if (index === 1 || index === 14) segments.push([left, top]);
      else if (index === 2 || index === 13) segments.push([top, right]);
      else if (index === 3 || index === 12) segments.push([left, right]);
      else if (index === 4 || index === 11) segments.push([right, bottom]);
      else if (index === 6 || index === 9) segments.push([top, bottom]);
      else if (index === 7 || index === 8) segments.push([left, bottom]);
      else if (index === 5) {
        segments.push([left, top]);
        segments.push([right, bottom]);
      } else if (index === 10) {
        segments.push([top, right]);
        segments.push([left, bottom]);
      }
    }
  }
  return segments;
}

/** Endpoints are matched at 1/64 of a view unit, as the tracer does. */
const key = (p: Point) => `${Math.round(p[0] * 64)},${Math.round(p[1] * 64)}`;

/** Walk the segment soup into polylines, following shared endpoints. */
function join(segments: [Point, Point][]): Point[][] {
  const adjacency = new Map<string, number[]>();
  segments.forEach(([a, b], i) => {
    for (const p of [a, b]) {
      const k = key(p);
      const at = adjacency.get(k);
      if (at) at.push(i);
      else adjacency.set(k, [i]);
    }
  });

  const used = new Array<boolean>(segments.length).fill(false);
  const paths: Point[][] = [];

  const walk = (start: number, fromEnd: boolean): Point[] => {
    const [a, b] = segments[start]!;
    used[start] = true;
    const chain: Point[] = fromEnd ? [b, a] : [a, b];
    for (;;) {
      const candidates = adjacency.get(key(chain[chain.length - 1]!));
      let next = -1;
      if (candidates) {
        for (const i of candidates) {
          if (!used[i]) {
            next = i;
            break;
          }
        }
      }
      if (next < 0) return chain;
      used[next] = true;
      const [na, nb] = segments[next]!;
      chain.push(key(na) === key(chain[chain.length - 1]!) ? nb : na);
    }
  };

  // Open ends first, so an isoline that leaves the frame is traced whole rather than split
  // in two at whatever segment happened to be visited first.
  for (const [k, indices] of adjacency) {
    if (indices.length !== 1) continue;
    const i = indices[0]!;
    if (used[i]) continue;
    paths.push(walk(i, key(segments[i]![1]) === k));
  }
  for (let i = 0; i < segments.length; i++) {
    if (!used[i]) paths.push(walk(i, false));
  }
  return paths;
}

/** Ramer-Douglas-Peucker, iterative so a long front cannot blow the stack. */
export function simplify(points: Point[], epsilon: number): Point[] {
  if (points.length < 3) return points;
  const keep = new Array<boolean>(points.length).fill(false);
  keep[0] = keep[points.length - 1] = true;
  const stack: [number, number][] = [[0, points.length - 1]];
  while (stack.length > 0) {
    const [first, last] = stack.pop()!;
    const [ax, ay] = points[first]!;
    const [bx, by] = points[last]!;
    const dx = bx - ax;
    const dy = by - ay;
    const norm = Math.hypot(dx, dy);
    let worst = 0;
    let worstAt = -1;
    for (let i = first + 1; i < last; i++) {
      const [px, py] = points[i]!;
      const distance =
        norm === 0
          ? Math.hypot(px - ax, py - ay)
          : Math.abs(dy * px - dx * py + bx * ay - by * ax) / norm;
      if (distance > worst) {
        worst = distance;
        worstAt = i;
      }
    }
    if (worst > epsilon && worstAt > 0) {
      keep[worstAt] = true;
      stack.push([first, worstAt]);
      stack.push([worstAt, last]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

/**
 * One animation loop of crests: `frameCount` frames, each a set of fronts one interval apart.
 *
 * **The spacing is exaggerated and the shape is not.** A 13.75 s swell has a 295 m wavelength,
 * which over this frame would be about 160 crests and a moiré pattern. The interval here is
 * chosen so the fronts are legible; where each one bends is the honest part.
 */
export function crestFrames(
  grid: DepthGrid,
  swell: Swell,
  frameCount = 16,
  tolerance = 0.7,
): Crest[][] {
  const field = travelTime(grid, swell);
  let span = 0;
  for (let i = 0; i < field.length; i++) {
    if (field[i] !== Infinity && field[i]! > span) span = field[i]!;
  }
  const interval = (CREST_SPACING * grid.metresPerUnit) / deepCelerity(swell.periodSeconds);
  // A chain shorter than two grid cells is an artefact of the tracer rather than a front:
  // nothing smaller than a couple of cells is resolved by soundings ~342 m apart. This
  // replaced a `reduced.length < 3` test, which used vertex count as a proxy for length and
  // got it backwards — a perfectly STRAIGHT crest simplifies to two points, so that rule
  // discarded 83 real fragments across a 16-frame loop and every crest of a flat sea.
  const minCrestLength =
    2 * Math.hypot(grid.viewWidth / (grid.cols - 1), grid.viewHeight / (grid.rows - 1));

  const frames: Crest[][] = [];
  for (let frame = 0; frame < frameCount; frame++) {
    const crests: Crest[] = [];
    for (let level = (frame / frameCount) * interval; level < span; level += interval) {
      for (const chain of join(isochroneSegments(grid, field, level))) {
        if (chainLength(chain) < minCrestLength) continue;
        const reduced = simplify(chain, tolerance);
        if (reduced.length < 2) continue;
        crests.push({ points: reduced });
      }
    }
    frames.push(crests);
  }
  return frames;
}
