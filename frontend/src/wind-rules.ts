/**
 * How a wind dart moves, and which way it points (#123).
 *
 * **Darts, not streamlines, and the reason is honesty rather than taste.** The map's wind comes
 * from twenty-five sampled points. A flowing field drawn between them would imply a continuous
 * measurement that does not exist; one dart per fetched point is literally what the data is.
 * Comets and meteorological barbs were both built in the prototype and rejected.
 *
 * **The known cost, accepted when darts were chosen: speed lives entirely in the motion**, so a
 * still frame of this map — a screenshot, or a reader who has asked for reduced motion — shows
 * direction and not strength. If that ever matters, comets are the fix and the prototype has
 * the code.
 */

/** Seconds a dart takes to travel one hop along its own heading. */
const SECONDS_PER_HOP_AT_UNIT_SPEED = 33;

/**
 * The speed at or below which the map draws a dart still.
 *
 * **A stated rule, not a clamp, and the difference matters.** This was `Math.min(33, 33/speed)`,
 * which silently made every speed under 1 km/h drift at 33 s per hop — so a 0.5 km/h wind moved
 * at twice the rate `33 / speed` names, in the one place on the map where speed appears at all.
 * The review of #123 caught it. Below a kilometre an hour there is nothing to show, so the map
 * says so by holding the dart still, and `wind-rules.test.ts` asserts that boundary from both
 * sides rather than only at zero.
 */
const CALM_KMH = 1;

/**
 * Seconds per hop for a calm.
 *
 * `33 / 0` is Infinity, which reaches CSS as `animation-duration: Infinitys`, fails to parse,
 * and leaves the dart drifting at whatever the previous rule set — a calm rendered as the last
 * wind there happened to be. A flat calm is a fact and gets a number.
 */
const STILLEST = 33;

/**
 * Seconds per hop: faster wind, faster drift.
 *
 * This is the only place speed appears on the map, which is why `wind-rules.test.ts` pins the
 * ordering as well as the arithmetic.
 */
export function driftSeconds(speedKmh: number): number {
  if (!(speedKmh > CALM_KMH)) return STILLEST;
  return SECONDS_PER_HOP_AT_UNIT_SPEED / speedKmh;
}

/**
 * The bearing a dart points along: downwind, which is the reciprocal of the reported one.
 *
 * Open-Meteo's `wind_direction_10m` — and every meteorological bearing — is the direction the
 * wind blows **from**. A dart drawn along that bearing points into the wind, and a map of
 * arrows pointing the wrong way looks exactly as convincing as one pointing the right way.
 */
export function dartHeadingDeg(fromDirectionDeg: number): number {
  return (fromDirectionDeg + 180) % 360;
}

/** The frame's corners on the earth and in the viewBox, as `depth-grid.json` carries them. */
export interface Frame {
  latTop: number;
  latBottom: number;
  lonLeft: number;
  lonRight: number;
  viewWidth: number;
  viewHeight: number;
}

/**
 * A latitude and longitude as a point in the map's viewBox.
 *
 * Linear in both axes, which is what the tracer does: `contours.py` projects
 * equirectangularly with the longitude axis scaled by cos(latitude), and that scaling is
 * already baked into `viewWidth`. Re-applying it here would place the darts on a slightly
 * different map from the one under them.
 *
 * Row 0 is the northern edge, matching the soundings, so latitude runs the opposite way to y.
 */
export function toView(lat: number, lon: number, frame: Frame): [number, number] {
  const x = ((lon - frame.lonLeft) / (frame.lonRight - frame.lonLeft)) * frame.viewWidth;
  const y = ((frame.latTop - lat) / (frame.latTop - frame.latBottom)) * frame.viewHeight;
  return [x, y];
}
