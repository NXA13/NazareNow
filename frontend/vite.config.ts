import react from '@vitejs/plugin-react';
// Imported from vitest/config, not vite — only this one knows about the `test` key.
import { defineConfig } from 'vitest/config';

/**
 * The port the dev server is pinned to.
 *
 * Pinned, and strict so a clash fails loudly. Vite's default is to walk up from 5173 until it
 * finds a free port, which silently lands the app on an origin the backend's CORS whitelist does
 * not allow — a failure that only appears in the browser console. 5273 is chosen to sit clear of
 * the usual 5173-5176 range.
 *
 * Exported because `playwright.config.ts` needs the same number twice, for the base URL its
 * tests resolve against and for the server it waits on. Three copies of a port is ADR 0013's
 * hazard in miniature: nothing would have compared them, and the failure — a layout suite
 * silently testing whatever else was on 5273 — does not look like a wrong port.
 */
export const DEV_PORT = 5273;

export default defineConfig({
  plugins: [react()],
  server: {
    port: DEV_PORT,
    strictPort: true,
    // Development runs the same shape as the deployed host: ADR 0007 serves the page and
    // the API from one origin, with a reverse proxy sending `/api` to the backend. This is
    // that proxy, so `api.ts` can use relative paths in both places and a same-origin
    // fault is reproducible on a laptop rather than only on the Pi.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    // Vitest owns `src/**`; Playwright owns `e2e/**` through its own `testDir`. Two tools with
    // two globs is a boundary stated twice, which is usually where things drift — but not
    // silently here: a Playwright spec collected by vitest fails on importing
    // `@playwright/test`, and a vitest file collected by Playwright fails on the globals it
    // expects. A misfiled test breaks the run it lands in rather than disappearing from both.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Pinned so timestamp assertions are deterministic. Without it a test asserting a
    // rendered time passes or fails depending on the machine's zone.
    env: { TZ: 'UTC' },
  },
});
