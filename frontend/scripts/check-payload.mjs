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
 * device — and there is no host yet, so no field measurement is possible: deployment is #28 and
 * belongs to v3. Payload is the part of load time this repository actually controls, so it is
 * the part this repository can honestly be held to. It is a proxy, and naming it a proxy here
 * is the same courtesy the track record extends to the Proxy Target.
 *
 * **Gzip and not brotli**, because gzip is the floor every host serves and brotli is a saving a
 * deployment might or might not turn on. Measuring the better case would report a number no
 * reader is guaranteed.
 *
 * The budget exists to make a regression visible, not to be a target to fill. It sits a little
 * above what the site costs today, so pulling in a charting or date library — the usual way a
 * page of this size doubles — fails here rather than being discovered after v3 puts it on a
 * Raspberry Pi.
 */

import { gzipSync } from 'node:zlib';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Compressed kilobytes the whole first load may cost. Today it is about 75. */
const BUDGET_KB = 95;

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
