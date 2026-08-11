/**
 * The presentation helpers, tested directly.
 *
 * These are pure functions with no React in them, and the rounding fault below is invisible
 * at the component seam: it needs a specific input to show, and a component test would have
 * to smuggle that value through a fixture to reach it. Everything a reader actually *sees*
 * is still asserted through the rendered interface, in App.test.tsx and Forecast.test.tsx.
 *
 * The rounding case comes from the Slice 1 audit (#25).
 */

import { afterEach, describe, expect, it } from 'vitest';

import { compassPoint, formatTimestamp, formatValue } from './format';

describe('formatValue', () => {
  it('keeps the digits a reader needs and drops the ones they do not', () => {
    expect(formatValue(17.0)).toBe('17');
    expect(formatValue(8.1)).toBe('8.1');
    expect(formatValue(3.14159)).toBe('3.14');
  });

  it('rounds a half up rather than silently down', () => {
    // `toFixed` runs on the binary double, and 2.675 is really 2.67499999999999982…, so
    // it rounds *down* — the opposite of what "round to 2dp" reads as, on the numbers a
    // reader is most likely to notice because they end in a 5.
    //
    // Expected values here are what decimal arithmetic gives, not what any JavaScript
    // expression produces: deriving them the way the code does would pass by
    // construction and could never disagree with it.
    expect(formatValue(2.675)).toBe('2.68');
    expect(formatValue(1.005)).toBe('1.01');
    expect(formatValue(0.125)).toBe('0.13');
  });

  it('leaves a negative value rounding away from zero, not toward it', () => {
    // Nothing displays a negative reading today — but air temperature is the obvious
    // candidate the first cold snap, and a rounding rule that only holds for positives
    // is a trap laid for later.
    expect(formatValue(-2.675)).toBe('-2.68');
  });

  it('renders a non-finite value as its own text rather than running it through the shift', () => {
    // Documented behaviour, and documented behaviour that nothing checked: removing the
    // guard sends `Infinity` through `Number('Infinitye2')` and renders it as "NaN" — a
    // different wrong answer, and the one that looks like a missing reading rather than an
    // impossible one.
    expect(formatValue(Infinity)).toBe('Infinity');
    expect(formatValue(-Infinity)).toBe('-Infinity');
    expect(formatValue(NaN)).toBe('NaN');
  });
});

describe('compassPoint', () => {
  it('names each point in the order it sits on the rose', () => {
    // Asserted as literals, which is the whole point. Everywhere else in the suite a
    // bearing is checked by calling `compassPoint` on both sides of the expectation — the
    // function agreeing with itself, which passes for *any* ordering of the rose. Only one
    // literal existed anywhere ('WNW'), so transposing NE and ENE renamed a quarter of the
    // compass and left all 120 tests green. A swell direction decides whether a day works
    // at Praia do Norte, so the rose is not decoration.
    expect(compassPoint(0)).toBe('N');
    expect(compassPoint(22.5)).toBe('NNE');
    expect(compassPoint(45)).toBe('NE');
    expect(compassPoint(67.5)).toBe('ENE');
    expect(compassPoint(90)).toBe('E');
    expect(compassPoint(112.5)).toBe('ESE');
    expect(compassPoint(135)).toBe('SE');
    expect(compassPoint(157.5)).toBe('SSE');
    expect(compassPoint(180)).toBe('S');
    expect(compassPoint(202.5)).toBe('SSW');
    expect(compassPoint(225)).toBe('SW');
    expect(compassPoint(247.5)).toBe('WSW');
    expect(compassPoint(270)).toBe('W');
    expect(compassPoint(292.5)).toBe('WNW');
    expect(compassPoint(315)).toBe('NW');
    expect(compassPoint(337.5)).toBe('NNW');
  });

  it('rounds to the nearest point rather than truncating to the one below', () => {
    expect(compassPoint(298)).toBe('WNW');
    expect(compassPoint(11)).toBe('N');
    expect(compassPoint(12)).toBe('NNE');
  });

  it('wraps a bearing outside one turn instead of falling back to north', () => {
    // 360 and 0 are the same bearing, so the `?? 'N'` fallback answers that one correctly
    // by accident. A bearing below zero is the case that tells a real wrap from the
    // fallback, and nothing had ever passed one in.
    expect(compassPoint(360)).toBe('N');
    expect(compassPoint(450)).toBe('E');
    expect(compassPoint(-90)).toBe('W');
    expect(compassPoint(-22.5)).toBe('NNW');
  });
});

describe('formatTimestamp', () => {
  // `vite.config.ts` pins the suite to UTC so timestamp assertions are deterministic — which
  // also means a helper whose entire job is *leaving* UTC cannot be exercised there. In UTC,
  // converting and not converting produce the same string. So these set a zone and restore
  // it, the way Forecast.test.tsx does for the day label, and compare renderings against
  // each other rather than against a clock literal: the locale is not pinned, only the zone.
  afterEach(() => {
    process.env.TZ = 'UTC';
  });

  const INSTANT = '2026-02-13T09:04:11+00:00';

  it('renders the instant in the reader’s own zone', () => {
    // Replacing the whole localised render with `date.toISOString()` passed every test in
    // the suite: nothing anywhere asserted this function's output.
    const inUtc = formatTimestamp(INSTANT);
    process.env.TZ = 'Pacific/Auckland';
    const inAuckland = formatTimestamp(INSTANT);

    // 09:04 UTC is 22:04 the same evening in Auckland, so the two renderings must differ.
    expect(inAuckland).not.toBe(inUtc);
    // And it is a rendering for a reader, not the machine-readable form it started as.
    expect(inAuckland).not.toContain('T');
    expect(inAuckland).not.toContain('Z');
  });

  it('reads a timestamp carrying no zone as UTC rather than as the reader’s local time', () => {
    // The store keeps what the provider reported and some of it arrives naive — the
    // fixtures' own `observed_at` is `2026-02-13T09:00`. Without the appended `Z` that
    // string means a different instant in every zone, and UTC is the one zone where the
    // difference cannot show.
    process.env.TZ = 'Pacific/Auckland';

    expect(formatTimestamp('2026-02-13T09:00')).toBe(formatTimestamp('2026-02-13T09:00Z'));
  });

  it('gives back text it cannot read as a date, rather than inventing one', () => {
    expect(formatTimestamp('not a timestamp')).toBe('not a timestamp');
  });
});
