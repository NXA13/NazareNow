import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },
  // The build scripts run in Node, not a browser, so `process` and `console` are defined there
  // and nowhere else in this package. Declared for `scripts/` alone rather than globally: the
  // application code reaching for `process` should still be an error, which is most of the value
  // of the rule.
  {
    files: ['scripts/**/*.mjs'],
    languageOptions: {
      globals: {
        console: 'readonly',
        process: 'readonly',
        URL: 'readonly',
        // `fetch` and `Buffer` are here for `fetch-fonts.mjs`, the one script that reaches the
        // network — once, by hand, to replace a committed font. Granted to every script rather
        // than that one, because this config block is per-directory and carving out a single
        // file would claim a precision it does not have.
        fetch: 'readonly',
        Buffer: 'readonly',
      },
    },
  },
);
