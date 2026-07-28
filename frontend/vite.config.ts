import react from '@vitejs/plugin-react';
// Imported from vitest/config, not vite — only this one knows about the `test` key.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    // Pinned, and strict so a clash fails loudly. Vite's default is to walk up from
    // 5173 until it finds a free port, which silently lands the app on an origin the
    // backend's CORS whitelist does not allow — a failure that only appears in the
    // browser console. 5273 is chosen to sit clear of the usual 5173-5176 range.
    port: 5273,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
