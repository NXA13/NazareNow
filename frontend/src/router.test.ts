/**
 * What an address means, decided in one pure function.
 *
 * The rest of the router is a subscription to `hashchange`, which is the browser's and not
 * worth restating in a test. What is worth pinning is the mapping itself, and in particular
 * the fallback: an address nobody recognises must land on the forecast rather than on a blank
 * page, and a blank page is exactly what a router that returns nothing produces.
 */

import { describe, expect, it } from 'vitest';

import { routeOf } from './router';

describe('routeOf', () => {
  it('sends the empty address to the forecast', () => {
    expect(routeOf('')).toBe('forecast');
  });

  it('sends a bare hash to the forecast', () => {
    // What a browser leaves behind after a link to `#/` is followed and then cleared.
    expect(routeOf('#')).toBe('forecast');
    expect(routeOf('#/')).toBe('forecast');
  });

  it('sends the how-it-works address to that page', () => {
    expect(routeOf('#/how-it-works')).toBe('how-it-works');
  });

  it('sends an address nobody recognises to the forecast', () => {
    // A 404 the site cannot serve — there is no server in a hash route — so the only honest
    // answer is the page somebody arriving almost certainly wanted.
    expect(routeOf('#/track-record')).toBe('forecast');
    expect(routeOf('#/how-it-works/extra')).toBe('forecast');
    expect(routeOf('#nonsense')).toBe('forecast');
  });
});
