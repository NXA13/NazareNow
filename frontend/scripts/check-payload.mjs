/**
 * What this site costs to open, measured rather than assumed.
 *
 * Story 27 of #1 — "I want the site to load quickly, so that checking it is a habit rather than
 * a chore" — was the one story with nothing behind it at all. Not a failing check: no check.
 * Every other claim this project makes about itself is measured and published, and the page is
 * built to state its own limits, so an unmeasured performance claim was the odd one out.
 *
 * **What this measures, and what it does not.** It measures the compressed bytes a first-time
 * visitor downloads. It does not measure load time, which depends on a host, a network and a
 * device — and there is no host yet, so no field measurement is possible: deployment is #28,
 * which is live work again rather than parked for v3. Payload is the part of load time this
 * repository actually controls, so it is
 * the part this repository can honestly be held to. It is a proxy, and naming it a proxy here
 * is the same courtesy the track record extends to the Proxy Target.
 *
 * **Gzip and not brotli**, because gzip is the floor every host serves and brotli is a saving a
 * deployment might or might not turn on. Measuring the better case would report a number no
 * reader is guaranteed.
 *
 * The budget exists to make a regression visible, not to be a target to fill. It sits a little
 * above what the site costs today, so pulling in a charting or date library — the usual way a
 * page of this size doubles — fails here rather than being discovered after the site is on a
 * Raspberry Pi.
 *
 * **Raised once, from 95 kB to 125 kB, by #114.** The Ink visual system costs 42.75 kB gzipped
 * in fonts: Space Grotesk as one variable file, and IBM Plex Mono at two weights because it is
 * published as static faces. That is not a dependency that can come back out — it is the
 * typography the design is, and the acceptance criteria required self-hosting rather than a
 * CDN, so the bytes are ours to carry rather than somebody else's to serve.
 *
 * Three things were done before moving it rather than after:
 *
 * - **The faces are subset** to the 117 glyphs either page can render, which is what makes the
 *   figure 42.75 kB instead of about 400 kB for the full families.
 * - **The cheapest cut was measured and declined.** Dropping IBM Plex Mono 600 would save
 *   12.68 kB and take the total to 104.63 kB — still over 95. It would also flatten every
 *   figure on the page to one weight, and the day cards read by weight.
 * - **The new ceiling is still tight.** 125 kB leaves about 7.7 kB of headroom over today's
 *   117.31 kB, so a charting or date library still fails here, which was the whole point of
 *   having a budget at all.
 *
 * **Raised again, from 125 kB to 130 kB, by #121** — the sea floor. The canyon is the one shape
 * that makes Nazaré what it is and it has to come from soundings, so the geometry is not a
 * dependency that can come back out either. Measured rather than projected: the map costs
 * **4.30 kB gzipped**, taking the site from 121.31 kB to 125.61 kB.
 *
 * Three things were done before moving it rather than after:
 *
 * - **The geometry was simplified as far as the data allows, and no further.** The tracer's
 *   tolerance went from 0.9 px to 2.0, which is 120 m across this frame against soundings that
 *   are about 342 m apart — so it discards interpolation rather than measurement. Across the
 *   whole sweep from 0.9 to 2.5 the traced path count is 33: no contour, seamount or canyon wall
 *   is dropped at any tolerance, only vertex density changes. That saved 31% of the geometry,
 *   7.46 kB gzipped down to 5.16.
 * - **The headline figure was checked against the compressed one.** The geometry is ~20 kB of
 *   path data raw, which reads as unaffordable against 3.7 kB of headroom and is not: path data
 *   compresses hard, and the budget has always been measured gzipped.
 *
 * - **Only what is drawn is shipped.** The tracer knows seventeen depth levels and the page
 *   draws eight of them as bands; the other nine were being emitted, downloaded and never
 *   rendered. That was 2.11 kB — a third of what the map cost before it was noticed, and 42% of
 *   the geometry — found by the review of the same ticket rather than by the measurement, which
 *   had no way to see it.
 *
 * **Raised again, from 130 kB to 145 kB, by #122** — the swell. ADR 0016 is the argument: the
 * crests were to have been precomputed at build time for binned period and direction, and the
 * bins did not fit. Measured, a direction bin passes its own width through to the screen almost
 * undamped (10° in, 9.35° of front rotation out), so the bins could not be coarse, and fine ones
 * came to **302 kB** — 54 fields at 5.60 kB. Worse than the size: that cannot be bundled, so it
 * forces the fields to be fetched one at a time, and then *this check* has to stop summing
 * `dist/` because it would count 302 kB against a visitor who downloads 5.60 kB. The budget
 * would have been bought at the cost of the guard.
 *
 * So the page solves the refraction itself, against the live period and direction, and ships the
 * sea floor instead of pictures of it. Measured against a real build rather than projected:
 *
 * | | gzip | |
 * |---|---|---|
 * | before #122 | 125.61 kB | |
 * | the solve, the component and the decoder | 128.80 kB | **+3.19 kB** |
 * | plus the 12,826 soundings they read | 140.88 kB | **+12.08 kB** |
 *
 * Three things were done before moving it rather than after:
 *
 * - **The soundings are packed, and the packing was measured four ways.** As JSON numbers they
 *   are 13.72 kB gzipped; as int16 they are 11.93; delta-encoded along rows, 9.35; and 11.00 as
 *   base64 standalone, which is 12.08 inside a JS string literal. Deltas because neighbouring
 *   soundings are close in value, which is what gzip is good at.
 * - **The cheaper quantisation was measured and declined.** Rounding depth to 5 m instead of 1 m
 *   saves 3.70 kB. Celerity is `sqrt(g*d)`, so a 5 m quantum is a 50% speed error in 10 m of
 *   water — precisely the shoaling zone the map exists to explain. Removing one quantisation by
 *   introducing a worse one where it matters most is not a saving.
 * - **The 1.65 kB of base64 overhead is paid knowingly.** A raw `.bin` asset would be 9.35 kB,
 *   but it needs a second request, a loading state and a failure mode, on a page whose map must
 *   render in every state including "the conditions never arrived". The bundled import matches
 *   how `map-geometry.json` already reaches the page.
 *
 * 145 kB leaves about 4.1 kB, which is deliberately not enough for a library. #123's wind will
 * need its own raise, measured the same way.
 */

import { gzipSync } from 'node:zlib';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Compressed kilobytes the whole first load may cost. Today it is about 141, of which 43 is
 * the two fonts and 12 the soundings. See the note above for why it moved. */
const BUDGET_KB = 145;

// Through `fileURLToPath` rather than the URL's own `pathname`, which on Windows hands back
// `/C:/...` — a string `fs` cannot open, so the check reported "no dist/" on a tree that had one.
const DIST = fileURLToPath(new URL('../dist/', import.meta.url));

/** Every built file, since a budget that counted only JavaScript would miss a stylesheet or an
 * embedded font growing without limit. */
function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

let files;
try {
  files = filesUnder(DIST);
} catch {
  console.error('No dist/ to measure. Run `npm run build` first.');
  process.exit(1);
}

if (files.length === 0) {
  console.error('dist/ is empty. Run `npm run build` first.');
  process.exit(1);
}

const measured = files
  .map((path) => ({
    name: relative(DIST, path).replace(/\\/g, '/'),
    raw: statSync(path).size,
    gzip: gzipSync(readFileSync(path)).length,
  }))
  .sort((a, b) => b.gzip - a.gzip);

const total = measured.reduce((sum, file) => sum + file.gzip, 0);
const kb = (bytes) => (bytes / 1024).toFixed(2).padStart(8);

for (const file of measured) {
  console.log(`${kb(file.gzip)} kB gzip  (${kb(file.raw)} kB raw)  ${file.name}`);
}
console.log(`${kb(total)} kB gzip  total, against a budget of ${BUDGET_KB} kB`);

if (total > BUDGET_KB * 1024) {
  console.error(
    `\nFirst load is ${(total / 1024).toFixed(2)} kB gzipped, over the ${BUDGET_KB} kB budget.\n` +
      'Either the growth is worth it and the budget moves in the same commit, with the reason ' +
      'written down, or it is not and the dependency comes back out.',
  );
  process.exit(1);
}
