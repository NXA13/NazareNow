/**
 * Every API call must be same-origin.
 *
 * ADR 0007 puts the page and the API behind one wall, on one origin: the page at
 * `www.nazarenow.com`, the API under `www.nazarenow.com/api`. That is not tidiness. A
 * private page in front of a public `/api/conditions/forecast` is not private, because
 * that endpoint *is* the store — and one origin also removes CORS from the deployment
 * entirely, which matters because a drifting origin fails only in a browser, invisibly to
 * both test suites.
 *
 * So the thing worth pinning is not which host the frontend talks to. It is that it names
 * no host at all. An absolute URL baked into the bundle would reach a second origin, which
 * is either blocked or — worse — reachable without the password.
 *
 * `scripts/check-same-origin.mjs` makes the matching assertion against the built output,
 * where an absolute URL reaching the bundle some other way would otherwise slip past this.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';

import { fetchCurrentConditions, fetchForecast, fetchTrackRecord } from './api';
import { server } from './test/server';

/** The URLs the module actually requested, in the order it requested them. */
const requested: string[] = [];

function captureAndAnswer(path: string) {
  return http.get(`*${path}`, ({ request }) => {
    requested.push(request.url);
    return HttpResponse.json({});
  });
}

afterEach(() => {
  requested.length = 0;
});

describe('the API module names no origin of its own', () => {
  it.each([
    ['the track record', '/api/track-record', fetchTrackRecord],
    ['the forecast', '/api/conditions/forecast', fetchForecast],
    ['current conditions', '/api/conditions/current', fetchCurrentConditions],
  ])('requests %s from the page’s own origin', async (_name, path, fetcher) => {
    server.use(captureAndAnswer(path));

    // The fetchers validate their payloads, and an empty object fails that on purpose —
    // the assertion here is about where the request went, not what came back.
    await fetcher().catch(() => undefined);

    expect(requested).toHaveLength(1);
    const [url] = requested;
    expect(url).toBeDefined();
    expect(new URL(url!).origin).toBe(window.location.origin);
    expect(new URL(url!).pathname).toBe(path);
  });
});
