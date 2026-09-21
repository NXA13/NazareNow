/**
 * Types for `fetch-fonts.mjs`. `src/ink.test.ts` imports the repertoire from there rather than
 * restating it, so the list the subsets were cut against and the list the test checks the copy
 * against cannot drift apart — which is the only way that test could pass while a character on
 * the page had no glyph.
 */

/** Every character the subsets carry, and therefore every character either page may render. */
export const REPERTOIRE: string;
