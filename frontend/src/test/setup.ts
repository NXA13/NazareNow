/**
 * Test setup shared by every frontend test.
 *
 * The frontend seam is the rendered interface with the API mocked at the network
 * boundary. MSW intercepts real fetch calls, so components are exercised exactly as
 * they run in a browser — no hand-injected fakes, no stubbed modules.
 *
 * `onUnhandledRequest: 'error'` is deliberate: any request a test did not explicitly
 * mock fails loudly. That is what guarantees no test reaches a third-party service.
 */

import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';

import { server } from './server';

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
});

afterAll(() => server.close());
