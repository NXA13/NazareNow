/**
 * The two rules a wind dart obeys, tested away from React.
 *
 * Both are small enough to look trivial and neither is: the drift rate is the *only* place
 * speed appears on the map (#123 accepts that a still frame cannot show it), and the heading
 * is a reciprocal, which is the kind of thing that is wrong by 180° for a year before anyone
 * notices, because a map of arrows always looks plausible.
 */

import { describe, expect, it } from 'vitest';

import { conditionsGrid } from './test/handlers';
import { dartHeadingDeg, driftSeconds, toView } from './wind-rules';

describe('driftSeconds', () => {
  it('takes 33 / speed seconds per hop, as the spec names it', () => {
    // Expected values worked out by hand from the rule, not from the function.
    expect(driftSeconds(33)).toBeCloseTo(1, 5);
    expect(driftSeconds(10)).toBeCloseTo(3.3, 5);
    expect(driftSeconds(45)).toBeCloseTo(0.7333333, 5);
  });

  it('makes faster wind drift faster, which is the whole claim', () => {
    // Speed lives entirely in the motion. If this ordering ever inverted, the map would be
    // saying the opposite of the truth while looking exactly as convincing.
    const speeds = [5, 10, 20, 33, 45, 70];
    const times = speeds.map(driftSeconds);
    for (let i = 1; i < times.length; i++) {
      expect(times[i]!, `${speeds[i]} km/h should hop quicker than ${speeds[i - 1]}`).toBeLessThan(
        times[i - 1]!,
      );
    }
  });

  it('gives a still dart rather than an infinite one when the air is dead', () => {
    // `33 / 0` is Infinity, which reaches CSS as `animation-duration: Infinitys` and is
    // dropped — leaving a dart drifting at whatever the previous rule said. A calm has to be
    // a decision, not a division.
    expect(Number.isFinite(driftSeconds(0))).toBe(true);
    // The law is that nothing drifts slower than a calm. Not "slower than 1 km/h": the cap
    // and the rule meet exactly at 1 km/h (33 / 1 = 33), so those two are legitimately equal.
    for (const speed of [1, 5, 20, 50]) {
      expect(driftSeconds(speed)).toBeLessThanOrEqual(driftSeconds(0));
    }
  });
});

describe('dartHeadingDeg', () => {
  it('points downwind, which is the reciprocal of the reported bearing', () => {
    // Open-Meteo's `wind_direction_10m` is the direction the wind blows FROM. A dart drawn
    // along that bearing points into the wind — backwards — and still looks like a wind map.
    expect(dartHeadingDeg(0)).toBe(180);
    expect(dartHeadingDeg(270)).toBe(90);
    expect(dartHeadingDeg(90)).toBe(270);
  });

  it('wraps rather than running past the compass', () => {
    expect(dartHeadingDeg(200)).toBe(20);
    expect(dartHeadingDeg(359)).toBe(179);
  });
});

describe('placing a point on the frame', () => {
  // The bounds come from `depth-grid.json`, written by the same build step that traced the
  // contours, so the page cannot hold a different opinion about where this map is than the
  // tracer does. `open_meteo.py` fetches the wind grid over exactly these bounds so that "a
  // wind glyph can never sit outside the drawn map" — a promise this function has to keep.
  const frame = {
    latTop: 39.82,
    latBottom: 39.4,
    lonLeft: -9.52,
    lonRight: -9.04,
    viewWidth: 686.8,
    viewHeight: 780,
  };

  it('puts the frame corners on the viewBox corners', () => {
    expect(toView(39.82, -9.52, frame)).toEqual([0, 0]);
    expect(toView(39.4, -9.04, frame)).toEqual([686.8, 780]);
  });

  it('puts north at the top, which is the one that reads plausible either way up', () => {
    const [, northY] = toView(39.82, -9.2, frame);
    const [, southY] = toView(39.4, -9.2, frame);
    expect(northY).toBeLessThan(southY);
  });

  it('puts east to the right', () => {
    const [westX] = toView(39.6, -9.52, frame);
    const [eastX] = toView(39.6, -9.04, frame);
    expect(eastX).toBeGreaterThan(westX);
  });

  it('keeps every point of the fetched grid inside the drawn frame', () => {
    // The grid's corners sit ON the bounds rather than at cell centres, so this is the
    // boundary case rather than a comfortable interior one.
    for (const point of conditionsGrid.points) {
      const [x, y] = toView(point.latitude, point.longitude, frame);
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(frame.viewWidth);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(frame.viewHeight);
    }
  });
});
