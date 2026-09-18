/**
 * Layout, measured in a browser that actually does layout.
 *
 * The rest of this suite runs in jsdom, which is right for everything it is asked: what the page
 * renders, what it refuses to imply, which fields are read. jsdom does **no layout at all** —
 * every element is 0x0 and `scrollHeight` is 0 — so a promise like "nothing scrolls at this
 * viewport" cannot be tested there. It cannot even be tested badly there; it silently passes.
 *
 * #115, #117 and #118 each turn on a layout outcome ("the test names the viewport it checked",
 * "the column's height still satisfies the no-scroll promise", "a test asserts that rather than a
 * human eyeballing it"). So the browser arrives here, once, and those three tickets share it.
 *
 * **Kept deliberately small.** This is not a second test suite for behaviour — behaviour is
 * already covered in jsdom, closer to the code and faster. What belongs here is what only a
 * layout engine can answer: heights, overflow, and how those change as the window resizes.
 *
 * The API is stubbed per test from the same fixtures the jsdom suite uses (`src/test/handlers`),
 * so this needs no backend and no network, and a layout failure means the layout changed rather
 * than the sea did.
 */

import { defineConfig, devices } from '@playwright/test';

import { DEV_PORT } from './vite.config';

/** The dev server's own address, derived from the port Vite is pinned to rather than written
 * again here. */
const ORIGIN = `http://localhost:${DEV_PORT}`;

/** The desktop viewport the no-scroll promise is made at, named in one place so a test cannot
 * quietly check a different one than it reports. A common laptop size, and the smallest of the
 * usual desktop widths — the promise is worth least if it only holds on a large monitor. */
export const DESKTOP = { width: 1440, height: 900 };

/** Where the phone is only asked to stay legible. #115 explicitly does not design this. */
export const NARROW = { width: 390, height: 844 };

export default defineConfig({
  testDir: './e2e',
  // Vitest owns `src/**`; this owns `e2e/**`, and neither picks up the other's files. The vitest
  // config names the same boundary from its side.
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: ORIGIN,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: DESKTOP },
    },
  ],
  // Vite's dev server, reused if one is already running locally so a `npm run dev` in another
  // terminal is not fought over. In CI there is never one, so it starts and stops with the run.
  webServer: {
    command: 'npm run dev',
    url: ORIGIN,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
