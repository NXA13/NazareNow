/**
 * Types for `check-contrast.mjs`, so `src/ink.test.ts` can import the measurement instead of
 * reimplementing it. The script itself stays plain JavaScript: it runs under bare `node` in CI
 * beside `check-payload.mjs`, and a build step between a check and the thing it checks is a
 * place for the two to drift apart.
 */

/** A `--name: value` map of every token declared in the sheet. */
export function parseTokens(css: string): Map<string, string>;

/** `#rgb`, `#rrggbb` or `rgba(...)` as channels in 0-255 and an alpha in 0-1. */
export function parseColour(value: string): { channels: number[]; alpha: number };

/** The WCAG contrast ratio between a foreground and the backdrop it is composited over. */
export function contrastRatio(
  foreground: { channels: number[]; alpha: number },
  backdrop: { channels: number[]; alpha: number },
): number;

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
