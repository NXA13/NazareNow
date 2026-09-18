/**
 * Which of the two pages the address bar is asking for.
 *
 * About a kilobyte, hand-rolled, and that is the point. React Router costs roughly 20 kB
 * gzipped — most of the payload increase v2 has to spend on real bathymetry — to solve a
 * problem this site has exactly two instances of. `check-payload.mjs` exists to make that
 * kind of import fail loudly rather than be discovered on a Raspberry Pi.
 *
 * **A hash route rather than a path, because a path route is a promise somebody else has to
 * keep.** `/how-it-works` survives a reload only if whatever serves the files rewrites unknown
 * paths back to `index.html`. That rewrite lives in a web server's configuration, which is not
 * in this repository and is not covered by any test in it — so a path router would ship a page
 * that works until somebody presses F5, and move the fix somewhere this project cannot see it.
 * A hash never reaches the server at all.
 *
 * Navigation itself is the browser's, not this module's: the links are ordinary anchors, for
 * the reasons written where they are rendered. This only listens for the result.
 */

import { useEffect, useState } from 'react';

export type Route = 'forecast' | 'how-it-works';

/**
 * The address each page answers to.
 *
 * One map, read in both directions: the nav renders these as its `href`s and the router
 * matches them coming back. Spelling them twice — once as a link and once as a route — is the
 * version of this that fails silently, because a mistyped `href` is not an error. It is an
 * address nobody recognises, and an address nobody recognises is the forecast.
 */
export const ADDRESS: Record<Route, string> = {
  forecast: '#/',
  'how-it-works': '#/how-it-works',
};

const ROUTES: Record<string, Route> = Object.fromEntries(
  Object.entries(ADDRESS).map(([route, hash]) => [hash, route as Route]),
);

/**
 * The address, as a page.
 *
 * Anything unrecognised is the forecast — including `''` and a bare `'#'`, which is what a
 * browser leaves behind and is why the forecast is the fallback rather than an entry in the
 * map. A hash route has no server to answer with a 404, so the only decision available is
 * which page a wrong address lands on, and a router that matched nothing would render nothing.
 */
export function routeOf(hash: string): Route {
  return ROUTES[hash] ?? 'forecast';
}

/** The current page, kept in step with the address bar for as long as the component lives. */
export function useRoute(): Route {
  const [route, setRoute] = useState(() => routeOf(window.location.hash));

  useEffect(() => {
    const syncFromHash = () => setRoute(routeOf(window.location.hash));
    window.addEventListener('hashchange', syncFromHash);
    // Once immediately: the address can change between the first render and this
    // subscription — a link followed during hydration, or a test setting the hash — and a
    // listener alone would never hear about the change it missed.
    syncFromHash();
    return () => window.removeEventListener('hashchange', syncFromHash);
  }, []);

  return route;
}
