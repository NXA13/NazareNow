/**
 * The sea floor, unpacked.
 *
 * The soundings ship as int16 deltas in base64 rather than as JSON numbers: 11.00 kB gzipped
 * against 13.72 kB, for 12,826 readings the solve needs in full (ADR 0016). The encoder is in
 * `scripts/map/contours.py`; this is the other half, and a decoder that silently drifted would
 * hand the refraction solve a different sea without anything failing.
 *
 * Tested against a fixture small enough to check by eye, so the test knows the answer
 * independently rather than agreeing with whatever the encoder emitted.
 */

import { describe, expect, it } from 'vitest';

import { decodeDepthGrid } from './depth-grid';

/**
 * Six readings: 0, -1, -300, -300, -299, 32 metres.
 * As deltas: 0, -1, -299, 0, 1, 331 — little-endian int16, then base64.
 */
const SIX_READINGS = 'AAD//9X+AAABAEsB';

describe('decodeDepthGrid', () => {
  it('rebuilds the readings from their deltas', () => {
    const grid = decodeDepthGrid({ rows: 2, cols: 3, deltas: SIX_READINGS });
    expect(Array.from(grid)).toEqual([0, -1, -300, -300, -299, 32]);
  });

  it('gives back exactly one reading per cell', () => {
    const grid = decodeDepthGrid({ rows: 2, cols: 3, deltas: SIX_READINGS });
    expect(grid.length).toBe(6);
  });

  it('keeps land positive and sea negative, which is the sign the solve reads', () => {
    const grid = decodeDepthGrid({ rows: 2, cols: 3, deltas: SIX_READINGS });
    // 32 m is the clifftop; everything below zero is water. A decoder that dropped the sign
    // would turn the whole Atlantic into land and the solve would emit nothing at all.
    expect(grid[5]).toBeGreaterThan(0);
    expect(grid[2]).toBeLessThan(0);
  });
});
