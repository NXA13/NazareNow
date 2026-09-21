/**
 * No built file may name an origin of its own.
 *
 * ADR 0007 serves the page and the API from one origin, behind one wall. `src/api.test.ts`
 * asserts that at the module seam; this asserts it against the bytes actually shipped,
 * which is the only place a build-time mistake can be seen. A `.env` file in the build
 * directory, a stray absolute URL in a component, or a well-meant "point it at the Pi"
 * change would all pass the unit test and fail here.
 *
 * **Why an absolute URL is not merely untidy.** The deployment's password sits on the
 * reverse proxy in front of one origin. A bundle that fetches a second origin either has
 * its requests blocked by the browser — the site silently showing nothing — or reaches a
 * backend that the wall does not cover, and `/api/conditions/forecast` *is* the store.
 *
 * Localhost is called out separately because it is the likeliest mistake and the most
 * confusing symptom: a page that works perfectly for the person who built it and is blank
 * for everyone else.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

// Through `fileURLToPath` for the same Windows reason as check-payload.mjs: the URL's own
// `pathname` hands back `/C:/...`, which `fs` cannot open.
const DIST = fileURLToPath(new URL('../dist/', import.meta.url));

/** Text files worth scanning. An image cannot issue a fetch. */
const SCANNED = /\.(js|mjs|cjs|css|html|json|map)$/;

/**
 * An `http://` or `https://` URL followed by something that looks like this app's own API
 * path. Matching bare origins would flag every documentation link and schema URL the
 * bundle legitimately contains.
 */
const ABSOLUTE_API_URL = /https?:\/\/[^\s"'`)]*\/api\//g;

/** Any localhost reference at all, which is never correct in a built artefact. */
const LOCALHOST = /https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/g;

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
  console.error('No dist/ to check. Run `npm run build` first.');
  process.exit(1);
}

const offences = [];
for (const path of files) {
  if (!SCANNED.test(path)) continue;
  const contents = readFileSync(path, 'utf8');
  const name = relative(DIST, path).replace(/\\/g, '/');

  for (const [pattern, what] of [
    [ABSOLUTE_API_URL, 'an absolute API URL'],
    [LOCALHOST, 'a localhost reference'],
  ]) {
    for (const match of contents.matchAll(pattern)) {
      offences.push(`${name}: ${what} — ${match[0]}`);
    }
  }
}

if (offences.length > 0) {
  console.error('The built site names an origin of its own:\n');
  for (const offence of offences) console.error(`  ${offence}`);
  console.error(
    '\nADR 0007 serves the page and the API from one origin. A built bundle that names a ' +
      'host either has its requests blocked by the browser, or reaches a backend the ' +
      'password does not cover. Use a relative path.',
  );
  process.exit(1);
}

console.log(`Checked ${files.length} built files: every request is same-origin.`);
