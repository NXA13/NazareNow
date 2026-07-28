/**
 * The mock API server every frontend test runs against.
 *
 * It is seeded with the default happy-path handlers. A test needing something else —
 * an error, a delay, different data — overrides them with `server.use(...)` rather
 * than editing this file or repeating the default in every test.
 */

import { setupServer } from 'msw/node';

import { handlers } from './handlers';

export const server = setupServer(...handlers);
