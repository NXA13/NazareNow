/**
 * Types for `check-contrast.mjs`, so `src/ink.test.ts` can import the measurement instead of
 * reimplementing it. The script itself stays plain JavaScript: it runs under bare `node`
 * beside `check-payload.mjs`, and a build step between a check and the thing it checks is a
 * place for the two to drift apart.
 *
 * **This file restates a contract that lives in JavaScript, which is ADR 0013's named hazard**
 * — "one quantity wearing two names across a file boundary, with nothing checking they mean
 * the same thing". `scripts/` sits outside `tsconfig.json`'s `include`, so `tsc` never reads
 * the `.mjs` and cannot compare the two. What closes it is a test rather than the compiler:
 * `src/ink.test.ts` asserts, at runtime, that every export declared here exists and has the
 * shape declared for it. A field renamed in the script fails that test instead of silently
 * type-checking against a description that is no longer true.
 */

/** A colour as this script handles one: channels in 0-255, and an alpha in 0-1 that matters,
 * because a translucent token has to be composited before it can be measured. */
export interface Colour {
  channels: number[];
  alpha: number;
}

/** A `--name: value` map of every token declared in the sheet. */
export function parseTokens(css: string): Map<string, string>;

/** `#rgb`, `#rrggbb` or `rgba(...)` as a `Colour`. */
export function parseColour(value: string): Colour;

/** The WCAG contrast ratio between a foreground and the backdrop it is composited over. */
export function contrastRatio(foreground: Colour, backdrop: Colour): number;

export interface MeasuredPair {
  /** The foreground token, e.g. `--ink-go`. */
  fore: string;
  /** The token for the ground it actually sits on. */
  back: string;
  /** The ratio it must clear, or `null` where it is reported but not gated. */
  gate: number | null;
  /** Why this pair is measured, and why it is or is not gated. */
  why: string;
  ratio: number;
  passes: boolean;
}

export const PAIRS: Omit<MeasuredPair, 'ratio' | 'passes'>[];

/** Every pair measured against the tokens sheet, or against `css` when one is supplied. */
export function measure(css?: string): MeasuredPair[];
