/**
 * Whether the calling module is being run as a script, rather than imported.
 *
 * Both `check-contrast.mjs` and `fetch-fonts.mjs` need this, and the reasoning is subtle enough
 * that keeping two copies meant having it wrong in one of them eventually: `src/ink.test.ts`
 * imports from both of them through Vite, where `import.meta.url` is **not** a `file:` URL. So
 * `fileURLToPath(import.meta.url)` throws under the test runner, and a top-level call to it
 * takes the whole suite down before a single assertion runs — which is exactly how this was
 * found. The `file:` guard comes first for that reason; the argv comparison never runs in a
 * test.
 *
 * Anything a script may do only as a script goes behind this: reading the filesystem from a
 * path relative to itself, printing a report, and calling `process.exit`.
 */

import { fileURLToPath } from 'node:url';

/**
 * @param {string} moduleUrl the calling module's own `import.meta.url`
 * @returns {boolean} true only when Node was pointed at that module directly
 */
export function runAsScript(moduleUrl) {
  if (!moduleUrl.startsWith('file:')) {
    return false;
  }
  return process.argv[1] === fileURLToPath(moduleUrl);
}
