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

import { describe, expect, it } from 'vitest';

import { formatValue } from './format';

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
});
