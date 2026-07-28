/**
 * The mock API server every frontend test runs against.
 *
 * Handlers here are the default happy path. A test that needs something else — an
 * error, a slow response, different data — overrides them with `server.use(...)`
 * rather than editing this file.
 */

import { setupServer } from 'msw/node';

export const server = setupServer();
