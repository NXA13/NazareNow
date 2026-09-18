/**
 * A number, in the face numbers are set in (#114).
 *
 * The tables, the tiles and the day cards ask for IBM Plex Mono by selector, because everything
 * in them is a figure. Prose cannot: `format.ts` returns strings, and a sentence like "Plausibly
 * 6.42m to 8.79m" is one text node with a figure buried in the middle of it.
 *
 * `tokens.css` gets most of the way there with a digit-scoped face at the front of
 * `--font-text`, which puts every digit on both pages in Plex wherever it sits. What that cannot
 * reach is the characters a number shares with prose — the decimal point, the comma, the unit —
 * because a `unicode-range` claiming those would set every full stop in the site's copy in the
 * mono face. So "6.42m" came out as mono digits with a Space Grotesk dot and m.
 *
 * This is the other half: wrap the figure and the whole thing is mono, separator and unit
 * included. #114 asks that no number is left in the text face, and a decimal point between two
 * digits is part of the number.
 *
 * **Use this for a figure that lands in prose.** Inside a table cell, a `.value` or a `.tier`'s
 * `dd` it is redundant — those are already mono by selector — and the digit-scoped face stays as
 * the backstop for a bare count interpolated without either.
 *
 * It renders a `span` with no layout of its own, so `textContent` is unchanged and a figure
 * still reads as one word to a screen reader.
 */

import type { ReactNode } from 'react';

export function Figure({ children }: { children: ReactNode }) {
  return <span className="figure">{children}</span>;
}
