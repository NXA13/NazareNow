/**
 * The shell both pages share: the masthead, the navigation, and which page is showing.
 *
 * Everything that fetches or renders a figure lives in `Home` or `HowItWorks`. This file
 * decides only which of the two is on screen, so the redesign tickets that follow can rebuild
 * a page without touching the frame around it.
 */

import { Home } from './Home';
import { HowItWorks } from './HowItWorks';
import { ADDRESS, useRoute, type Route } from './router';
import './App.css';

/** The two pages, in the order they are offered. The addresses come from the router rather
 * than being written again here — see `ADDRESS`. */
const PAGES: { route: Route; label: string }[] = [
  { route: 'forecast', label: 'Forecast' },
  { route: 'how-it-works', label: 'How it works' },
];

export function App() {
  const route = useRoute();

  return (
    /* Which width this page is read at. The home page is an instrument and takes the screen;
       the second page is prose and is bounded by the line length an eye can follow. The router
       already knows which is showing, so the frame asks it rather than keeping its own copy. */
    <main className={route === 'how-it-works' ? 'page-reading' : 'page-forecast'}>
      <header>
        <h1>NazareNow</h1>
        <p className="tagline">When will Praia do Norte produce giant waves?</p>

        {/* Ordinary anchors, and the one decision in this file worth stating. Following a
            link, opening it in a new tab, copying its address and pressing Back are all
            behaviour the browser already has; a click handler on a non-link reimplements the
            first, loses the other three, and looks identical in a screenshot. */}
        <nav aria-label="Pages">
          {PAGES.map((page) => (
            <a
              key={page.route}
              href={ADDRESS[page.route]}
              // For a reader who cannot see which link is lit. The styling that marks the
              // current page hangs off this attribute rather than sitting beside it, so what
              // is seen and what is announced cannot drift apart.
              aria-current={route === page.route ? 'page' : undefined}
            >
              {page.label}
            </a>
          ))}
        </nav>
      </header>

      {route === 'how-it-works' ? <HowItWorks /> : <Home />}
    </main>
  );
}
