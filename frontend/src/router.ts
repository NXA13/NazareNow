/**
 * Which of the two pages the address bar is asking for.
 *
 * About a kilobyte, hand-rolled, and that is the point. React Router costs roughly 20 kB
 * gzipped — most of the payload increase v2 has to spend on real bathymetry — to solve a
 * problem this site has exactly two instances of. `check-payload.mjs` exists to make that
 * kind of import fail loudly rather than be discovered on a Raspberry Pi.
 *
 * **A hash route rather than a path, because a path route is a promise about a server.**
 * `/how-it-works` only survives a reload if whatever serves the files rewrites unknown paths
 * to `index.html`. There is no host yet — deployment is #28 and belongs to v3 — so a path
 * router would ship a page that works until somebody presses F5 on it, and would move the fix
 * into a configuration file this repository does not own. A hash never reaches the server.
 *
 * **Navigation itself is not implemented here, deliberately.** The links are ordinary anchors
 * with an `href`, so following one, opening it in a new tab, copying it, and the Back button
 * are all the browser's own behaviour rather than a reimplementation of it. This module only
 * listens for the result.
 */

import { useEffect, useState } from 'react';

export type Route = 'forecast' | 'how-it-works';

/** Every address the site answers to. The forecast is the fallback rather than an entry: it
 * is what an unrecognised address resolves to, so listing it would imply the site has a
 * single correct spelling for the home page, and `''`, `'#'` and `'#/'` are all of them. */
const ROUTES: Record<string, Route> = {
  '#/how-it-works': 'how-it-works',
};

/**
 * The address, as a page.
 *
 * Anything unrecognised is the forecast. A hash route has no server to answer with a 404, so
 * the only decision available is which page a wrong address lands on — and a router that
 * matched nothing would render nothing, which is the blank page this project keeps finding at
 * the end of its own mistakes.
 */
export function routeOf(hash: string): Route {
  return ROUTES[hash] ?? 'forecast';
}

/** The current page, kept in step with the address bar for as long as the component lives. */
export function useRoute(): Route {
  const [route, setRoute] = useState(() => routeOf(window.location.hash));

  useEffect(() => {
    const read = () => setRoute(routeOf(window.location.hash));
    window.addEventListener('hashchange', read);
    // Once immediately: the address can change between the first render and this
    // subscription — a link followed during hydration, or a test setting the hash — and a
    // listener alone would never hear about the change it missed.
    read();
    return () => window.removeEventListener('hashchange', read);
  }, []);

  return route;
}
