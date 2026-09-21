/**
 * Test setup shared by every frontend test.
 *
 * The frontend seam is the rendered interface with the API mocked at the network
 * boundary. MSW intercepts real fetch calls, so components are exercised exactly as
 * they run in a browser — no hand-injected fakes, no stubbed modules.
 *
 * `onUnhandledRequest: 'error'` is deliberate: any request a test did not explicitly
 * mock fails loudly. That is what guarantees no test reaches a third-party service.
 *
 * **The suite runs as a reader who has asked for reduced motion.** jsdom implements no
 * `matchMedia` at all, so `Crests`'s reduced-motion check saw `undefined`, took it for "motion
 * is fine", and advanced the crest phase on a timer — markup that changes on its own, in a
 * suite where `every-field-is-read.test.tsx` certifies a field unread by rendering twice and
 * comparing byte for byte.
 *
 * **This is a source of that variation, not a diagnosed cause of any particular failure.** CI
 * failed once on `GridPoint.swell_direction`, a field nothing reads; it did not reproduce
 * locally across repeated runs, and the more likely culprit — a helper that snapshotted before
 * the whole page had loaded — is fixed in that file. Both are removed rather than one being
 * blamed.
 *
 * So the whole suite holds the map still. What that costs is worth naming: no vitest test can
 * see the animation, and the drift is asserted in `e2e/wind.spec.ts` with the preference
 * actually set, in a browser that actually runs a cascade.
 */

import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { server } from './server';

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });

  window.matchMedia = ((query: string) => ({
    matches: query.includes('prefers-reduced-motion'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => server.close());
