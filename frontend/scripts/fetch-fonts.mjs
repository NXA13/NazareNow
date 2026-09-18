/**
 * The two Ink faces, fetched once, subset to what this site renders, and committed.
 *
 * #114 asks for both fonts to be served from this origin rather than from a third-party CDN,
 * because "the deployment is one origin behind one wall, and a font fetched from somebody
 * else's host is neither". So the files live in `src/fonts/` and go out with the build. This
 * script is how they got there, and re-running it is how they are replaced.
 *
 * **Nothing at build time or run time calls this.** `npm run build` needs no network: the
 * `.woff2` files are committed, and `tokens.css` names them by relative path. That is the
 * whole point — a build that silently reached for fonts.gstatic.com would have failed the
 * criterion while appearing to pass it.
 *
 * **Why Google's API does the subsetting.** Google's CSS endpoint accepts `text=` and returns
 * a face containing only those glyphs, already woff2. Subsetting locally would mean pulling in
 * `fonttools` (absent here) or a harfbuzz-backed npm package, for a worse result: the endpoint
 * subsets from the upstream source the family is actually published from. The cost is that
 * replacing a font needs network once, which is what committing the output buys back.
 *
 * **The known limit, stated rather than discovered.** A subset font covers the glyphs listed
 * in `REPERTOIRE` and nothing else. Every string this site renders is either literal English
 * copy, a number, or a unit from the API — all inside it — with one exception:
 * `formatTimestamp` calls `toLocaleString`, so a reader whose browser is set to another locale
 * gets that locale's month names ("set." in Portuguese, "9月" in Japanese). Those fall through
 * to the system stack in `--font-text`, which renders them correctly in a different face. A
 * full unhinted Latin-Extended pair to cover only the Portuguese case would cost around ten
 * times what the subsets cost, and would still not cover the Japanese one.
 */

import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

// Lazy, and script-only, for the reason `check-contrast.mjs` explains: `src/ink.test.ts`
// imports `REPERTOIRE` from this module through Vite, where `import.meta.url` is not a
// `file:` URL.
const fontsDir = () => fileURLToPath(new URL('../src/fonts/', import.meta.url));

const runAsScript = () =>
  import.meta.url.startsWith('file:') && process.argv[1] === fileURLToPath(import.meta.url);

/**
 * Every character this site can render, and therefore every glyph the subsets carry.
 *
 * Printable ASCII, because copy is English and numbers, units and compass points are ASCII.
 * Then a named list of what is not:
 *
 * - `°` — bearings and temperatures, from the API's `unit` fields.
 * - `é` — Nazaré, in the wordmark and in half the copy.
 * - `—` and `–` — the em dash this project's prose uses constantly, and an en dash for spans.
 * - `−` — a real minus sign, which `TrackRecord` uses for a negative bias so it cannot be
 *   misread as a hyphen.
 * - `…` and `→` — reachable in strings the backend sends.
 * - `×`, `·` — a multiplication sign and a middot, both of which appear in this kind of copy.
 * - the curly quotes — Prettier leaves apostrophes in copy alone, and a straight quote in
 *   prose that a later edit curls would otherwise be a silently missing glyph.
 * - `ç ã õ á í ó ú à` — Portuguese place names beyond Nazaré. Cheap here, and the failure
 *   they prevent (a broken place name on a site about a Portuguese beach) is not cheap.
 * - a non-breaking space, which keeps a number and its unit on one line.
 *
 * `src/ink.test.ts` fails when the source renders a character this list does not carry, so
 * the list cannot drift away from the copy without somebody being told.
 */
export const REPERTOIRE = [
  // Printable ASCII, space through tilde.
  ...Array.from({ length: 0x7e - 0x20 + 1 }, (_, index) => String.fromCharCode(0x20 + index)),
  ' ',
  '°',
  'é',
  '—',
  '–',
  '−',
  '…',
  '→',
  '×',
  '·',
  '‘',
  '’',
  '“',
  '”',
  'ç',
  'ã',
  'õ',
  'á',
  'í',
  'ó',
  'ú',
  'à',
].join('');

/**
 * What to fetch, and what each file is for.
 *
 * Space Grotesk is published as a variable font, so one file carries every weight from 400 to
 * 700 and the CSS can ask for any of them. IBM Plex Mono is published as separate static
 * faces, so each weight is its own download — which is why only two are taken. A third mono
 * weight would cost another file to buy a distinction nothing on either page makes.
 */
const WANTED = [
  { family: 'Space Grotesk', axis: 'wght@400..700', file: 'space-grotesk-variable.woff2' },
  { family: 'IBM Plex Mono', axis: 'wght@400', file: 'ibm-plex-mono-400.woff2' },
  { family: 'IBM Plex Mono', axis: 'wght@600', file: 'ibm-plex-mono-600.woff2' },
];

// Google serves woff2 only to a user agent it believes supports it. Asked as anything else it
// hands back truetype, which is roughly twice the bytes for the same glyphs.
const WOFF2_CAPABLE =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

async function fetchSubset({ family, axis, file }) {
  const url =
    `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family)}:${axis}` +
    `&text=${encodeURIComponent(REPERTOIRE)}`;

  const stylesheet = await fetch(url, { headers: { 'User-Agent': WOFF2_CAPABLE } });
  if (!stylesheet.ok) {
    throw new Error(`${family} ${axis}: the CSS endpoint answered ${stylesheet.status}`);
  }

  const css = await stylesheet.text();
  const sources = [...css.matchAll(/url\((https:\/\/[^)]+)\)\s*format\('woff2'\)/g)].map(
    (match) => match[1],
  );
  const unique = [...new Set(sources)];

  if (unique.length !== 1) {
    throw new Error(
      `${family} ${axis}: expected one woff2 for one weight, the endpoint offered ` +
        `${unique.length}. The family may have changed how it is published.`,
    );
  }

  const font = await fetch(unique[0], { headers: { 'User-Agent': WOFF2_CAPABLE } });
  if (!font.ok) {
    throw new Error(`${family} ${axis}: the font itself answered ${font.status}`);
  }

  const bytes = Buffer.from(await font.arrayBuffer());
  const directory = fontsDir();
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, file), bytes);
  return { family, axis, file, bytes: bytes.length };
}

async function main() {
  const fetched = [];
  for (const wanted of WANTED) {
    const path = join(fontsDir(), wanted.file);
    const before = existsSync(path) ? readFileSync(path).length : null;
    const result = await fetchSubset(wanted);
    fetched.push({ ...result, before });
  }

  const width = Math.max(...fetched.map((row) => row.file.length));
  for (const row of fetched) {
    const moved =
      row.before === null
        ? 'new'
        : row.before === row.bytes
          ? 'unchanged'
          : `was ${(row.before / 1024).toFixed(2)} kB`;
    console.log(
      `${row.file.padEnd(width)}  ${(row.bytes / 1024).toFixed(2).padStart(7)} kB  ` +
        `${row.family} ${row.axis}  (${moved})`,
    );
  }

  const total = fetched.reduce((sum, row) => sum + row.bytes, 0);
  console.log(
    `${'total'.padEnd(width)}  ${(total / 1024).toFixed(2).padStart(7)} kB  ` +
      `${REPERTOIRE.length} glyphs each`,
  );
  console.log(
    '\nwoff2 is brotli-compressed already, so these are close to what a reader downloads.\n' +
      'Run `npm run build && npm run check:payload` for the figure that counts.',
  );
}

if (runAsScript()) {
  await main();
}
