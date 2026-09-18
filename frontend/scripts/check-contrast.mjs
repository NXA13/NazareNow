/**
 * What the Ink palette actually contrasts at, measured rather than assumed.
 *
 * #114 asks for a near-black graphite ground with pastel statuses on it, and every acceptance
 * criterion in that ticket about colour is a claim that can be wrong quietly. A pastel green
 * that looks light in a mockup at 32 px is not necessarily readable at 0.7rem, and the way
 * that failure arrives is nobody ever checking — so this measures every foreground the
 * stylesheet puts on the ground and fails when one of them falls short.
 *
 * **Measured against the ground each colour is really used on**, which is not always
 * `--ink-page`: panels sit at `--ink-panel` and the dim status washes sit over panels, so a
 * ratio quoted against the page alone would flatter text that never appears there.
 *
 * The thresholds are WCAG 2.1 AA: 4.5:1 for text. Where a colour is decoration that repeats
 * something already in the text — the dim status washes behind a row, the `--ink-wind` grey
 * the map's darts will use — it is measured and reported but not gated, and the reason is
 * written beside it rather than left implied.
 *
 * Gzip is to payload what this is to colour: the floor a reader is actually guaranteed.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Resolved when it is needed rather than at import, and through `fileURLToPath` rather than
// the URL's `pathname`, which on Windows hands back `/C:/...` — the trap `check-payload.mjs`
// documents. Lazily, because the test suite imports this module through Vite, where
// `import.meta.url` is not a `file:` URL and resolving one at import time throws before a
// single assertion runs.
const tokensPath = () => fileURLToPath(new URL('../src/tokens.css', import.meta.url));

/** True only when this file is being run as a script, which is the only time it may read the
 * filesystem or exit the process. */
const runAsScript = () =>
  import.meta.url.startsWith('file:') && process.argv[1] === fileURLToPath(import.meta.url);

/** Every `--name: value` pair in the tokens sheet, which is the only place colour is defined. */
export function parseTokens(css) {
  const tokens = new Map();
  for (const [, name, value] of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    tokens.set(name, value.trim());
  }
  return tokens;
}

/** `#rgb`, `#rrggbb` or `rgba(r, g, b, a)` as channels in 0-255 plus an alpha in 0-1. */
export function parseColour(value) {
  const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const digits =
      hex[1].length === 3
        ? [...hex[1]].map((digit) => digit + digit)
        : [hex[1].slice(0, 2), hex[1].slice(2, 4), hex[1].slice(4, 6)];
    return { channels: digits.map((pair) => parseInt(pair, 16)), alpha: 1 };
  }

  const functional = value.match(/^rgba?\(([^)]+)\)$/i);
  if (functional) {
    const parts = functional[1]
      .split(/[,\s/]+/)
      .filter(Boolean)
      .map(Number);
    return { channels: parts.slice(0, 3), alpha: parts.length > 3 ? parts[3] : 1 };
  }

  throw new Error(`Not a colour this script can measure: ${value}`);
}

/**
 * A translucent colour as the opaque colour a reader actually sees, composited over its
 * backdrop. Without this step every `rgba()` token would be measured as though the ground
 * behind it were white, which is the one thing it never is here.
 */
function flatten(colour, backdrop) {
  return colour.channels.map((channel, index) =>
    Math.round(channel * colour.alpha + backdrop.channels[index] * (1 - colour.alpha)),
  );
}

/** WCAG relative luminance. */
function luminance(channels) {
  const [red, green, blue] = channels.map((channel) => {
    const proportion = channel / 255;
    return proportion <= 0.04045 ? proportion / 12.92 : Math.pow((proportion + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** WCAG contrast ratio between two colours, the lighter over the darker. */
export function contrastRatio(foreground, backdrop) {
  const over = luminance(flatten(foreground, backdrop));
  const under = luminance(flatten(backdrop, backdrop));
  const [lighter, darker] = over > under ? [over, under] : [under, over];
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Every foreground this stylesheet puts on a ground, the ground it is really on, and what it
 * has to clear.
 *
 * `gate: null` means measured and reported but not gated, with the reason in `why` — a wash
 * behind a row, or a colour the map has not drawn yet, is not the thing carrying the text.
 */
export const PAIRS = [
  { fore: '--ink-text', back: '--ink-page', gate: 4.5, why: 'body copy on the ground' },
  { fore: '--ink-text', back: '--ink-panel', gate: 4.5, why: 'body copy on a panel' },
  { fore: '--ink-muted', back: '--ink-page', gate: 4.5, why: 'labels, captions, quiet notes' },
  { fore: '--ink-muted', back: '--ink-panel', gate: 4.5, why: 'the same, inside a panel' },
  { fore: '--ink-main', back: '--ink-page', gate: 4.5, why: 'Ice: the wordmark, the nav, links' },
  { fore: '--ink-go', back: '--ink-page', gate: 4.5, why: 'a Go Call, the loudest thing here' },
  { fore: '--ink-go', back: '--ink-panel', gate: 4.5, why: 'a Go Call on a panel' },
  { fore: '--ink-watch', back: '--ink-page', gate: 4.5, why: 'a Watch' },
  { fore: '--ink-watch', back: '--ink-panel', gate: 4.5, why: 'a Watch on a panel' },
  { fore: '--ink-border', back: '--ink-page', gate: null, why: 'a hairline, not information' },
  {
    fore: '--ink-go-dim',
    back: '--ink-panel',
    gate: null,
    why: 'a wash behind a row; the call itself is in the text and the badge',
  },
  {
    fore: '--ink-watch-dim',
    back: '--ink-panel',
    gate: null,
    why: 'the same wash, for a Watch',
  },
  {
    fore: '--ink-wind',
    back: '--ink-deep',
    gate: null,
    why: 'the wind darts the map will carry (#123), deliberately quieter than the swell',
  },
];

/** Each pair measured, in the order above. */
export function measure(css = readFileSync(tokensPath(), 'utf8')) {
  const tokens = parseTokens(css);

  return PAIRS.map((pair) => {
    const missing = [pair.fore, pair.back].filter((name) => !tokens.has(name));
    if (missing.length > 0) {
      throw new Error(`tokens.css defines no ${missing.join(' and no ')}`);
    }

    const ratio = contrastRatio(
      parseColour(tokens.get(pair.fore)),
      parseColour(tokens.get(pair.back)),
    );
    return { ...pair, ratio, passes: pair.gate === null || ratio >= pair.gate };
  });
}

function main() {
  const measured = measure();
  const width = Math.max(...measured.map((row) => `${row.fore} on ${row.back}`.length));

  for (const row of measured) {
    const gate = row.gate === null ? 'not gated' : `needs ${row.gate.toFixed(1)}`;
    console.log(
      `${`${row.fore} on ${row.back}`.padEnd(width)}  ` +
        `${row.ratio.toFixed(2).padStart(6)}:1  ${gate.padEnd(11)}  ` +
        `${row.passes ? ' ' : '!'} ${row.why}`,
    );
  }

  const short = measured.filter((row) => !row.passes);
  if (short.length > 0) {
    console.error(
      `\n${short.length} colour${short.length === 1 ? '' : 's'} below the threshold:\n` +
        short
          .map(
            (row) => `  ${row.fore} on ${row.back} is ${row.ratio.toFixed(2)}:1, needs ${row.gate}`,
          )
          .join('\n') +
        '\nLighten the foreground rather than saturating it: saturating a status collapses the ' +
        'distinction between the three colour systems, which is the one thing #114 asks to keep.',
    );
    process.exit(1);
  }
}

// Only when run as a script. The suite imports `measure` and asserts on it, and a
// `process.exit` reached through an import would take the whole run down with it.
if (runAsScript()) {
  main();
}
