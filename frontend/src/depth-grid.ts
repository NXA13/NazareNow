/**
 * The sea floor, unpacked from the form it ships in.
 *
 * 12,826 GEBCO soundings, which the refraction solve reads in full rather than as contours
 * (ADR 0016). As JSON numbers they cost 13.72 kB gzipped; as int16 deltas in base64, 11.00 kB.
 * Metres, and the sign is the one the solve reads: negative below sea level, positive on land,
 * exactly as `bathymetry.json` stores it.
 *
 * Deltas rather than absolute values because neighbouring soundings are close in value, which
 * is what gzip is good at: 11.93 kB undelta'd against 9.35 kB delta'd before base64.
 *
 * Emitted by `scripts/map/contours.py`. Nothing regenerates it at build time and nothing needs
 * a network to.
 */

import packed from './depth-grid.json';
import type { DepthGrid } from './refraction';

export interface PackedDepthGrid {
  rows: number;
  cols: number;
  /** The frame's corners on the earth, for placing a lat/lon inside the viewBox. */
  latTop: number;
  latBottom: number;
  lonLeft: number;
  lonRight: number;
  /** The viewBox the grid maps onto, so the page and the tracer cannot disagree about it. */
  viewWidth: number;
  viewHeight: number;
  /** Metres per view unit, derived by the build step from these same soundings. */
  metresPerUnit: number;
  /** Little-endian int16 deltas, base64. */
  deltas: string;
}

/** Takes only the three fields it reads, so a caller with soundings and nothing else can use it. */
export function decodeDepthGrid(
  packed: Pick<PackedDepthGrid, 'rows' | 'cols' | 'deltas'>,
): Int16Array {
  const binary = atob(packed.deltas);
  const count = packed.rows * packed.cols;
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const deltas = new Int16Array(bytes.buffer, bytes.byteOffset, count);

  const elevation = new Int16Array(count);
  let running = 0;
  for (let i = 0; i < count; i++) {
    running += deltas[i]!;
    elevation[i] = running;
  }
  return elevation;
}

/**
 * The sea floor, decoded once for the life of the page.
 *
 * Assembled here rather than at each call site: the six-field literal was being written out in
 * both `Crests.tsx` and `refraction.parity.test.ts`, which is two places for the page and its
 * own parity check to start describing different seas.
 */
export const SEA_FLOOR: DepthGrid = {
  rows: packed.rows,
  cols: packed.cols,
  elevationMetres: decodeDepthGrid(packed),
  viewWidth: packed.viewWidth,
  viewHeight: packed.viewHeight,
  metresPerUnit: packed.metresPerUnit,
};

/** The frame's corners on the earth, as the build step measured them from the soundings. */
export const FRAME = {
  latTop: packed.latTop,
  latBottom: packed.latBottom,
  lonLeft: packed.lonLeft,
  lonRight: packed.lonRight,
  viewWidth: packed.viewWidth,
  viewHeight: packed.viewHeight,
};

export type Frame = typeof FRAME;
