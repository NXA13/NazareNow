/** Presentation helpers. Pure functions, no React, no fetching. */

const POINTS = [
  'N',
  'NNE',
  'NE',
  'ENE',
  'E',
  'ESE',
  'SE',
  'SSE',
  'S',
  'SSW',
  'SW',
  'WSW',
  'W',
  'WNW',
  'NW',
  'NNW',
];

/**
 * A degree bearing as a 16-point compass name.
 *
 * Shown alongside the number rather than instead of it: a reader should not need to
 * know that 298° is west-north-west, and a surfer checking the swell direction should
 * not have to trust our rounding.
 */
export function compassPoint(degrees: number): string {
  const index = Math.round((((degrees % 360) + 360) % 360) / 22.5) % POINTS.length;
  return POINTS[index] ?? 'N';
}

/**
 * Two decimal places at most, trailing zeros trimmed: 17.0 reads as "17", 8.1 stays "8.1".
 *
 * Rounds a half **away from zero**, which is what "to 2 decimal places" reads as. `toFixed`
 * does not: it rounds the underlying binary double, and 2.675 is really
 * 2.67499999999999982…, so `(2.675).toFixed(2)` is "2.67" and `(1.005).toFixed(2)` is
 * "1.00". The error only ever appears on values ending in a 5 — the ones a reader is most
 * likely to check by eye — and it always rounds down, so it reads as a systematic
 * understatement rather than as noise (#25).
 *
 * The shift is done through the decimal string rather than by multiplying by 100, because
 * `2.675 * 100` is 267.49999999999997 and reintroduces the same fault one step later.
 *
 * Two inputs are handled outside that rule, neither reachable from a reading this app
 * displays, both stated here rather than left for a reader to discover: a non-finite value
 * renders as its own text (`"NaN"`, `"Infinity"`), and a value already in exponential form
 * — magnitudes at or above 1e21, or below 1e-6 — falls back to `toFixed`, keeping the
 * half-down behaviour at a scale where the last two decimals mean nothing anyway.
 */
export function formatValue(value: number): string {
  if (!Number.isFinite(value)) {
    return String(value);
  }

  const decimal = String(Math.abs(value));
  // Already in exponential form (a magnitude no reading here has, but the guard costs
  // nothing): appending another exponent would produce NaN.
  if (decimal.includes('e') || decimal.includes('E')) {
    return String(Number(value.toFixed(2)));
  }

  const rounded = Math.round(Number(`${decimal}e2`)) / 100;
  return String(value < 0 ? -rounded : rounded);
}

/**
 * A reading as a reader sees it: the value formatted, its unit appended.
 *
 * One function so a figure cannot be rendered two ways in two places. The `aria-label` on
 * a day card used to interpolate raw values while the card body ran the same readings
 * through `formatValue`, so a screen reader was told "4.23456m" beside a card showing
 * "4.23" — and because `aria-label` overrides content, that reader could not reach the
 * shorter one (#25). A test now catches that, but a shared function means there is nothing
 * left to catch.
 */
export function formatReading(reading: { value: number; unit: string }): string {
  return `${formatValue(reading.value)}${reading.unit}`;
}

/**
 * A UTC timestamp rendered for a reader, in their local zone.
 *
 * The backend stores what the provider reported, which is UTC. Showing that verbatim
 * would be a small lie to anyone standing on the beach in Portugal.
 */
export function formatTimestamp(value: string): string {
  const withZone = /[Z+]|-\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  const date = new Date(withZone);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}
