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

/** Trim trailing zeros so 17.0 reads as "17" and 8.1 stays "8.1". */
export function formatValue(value: number): string {
  return String(Number(value.toFixed(2)));
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
