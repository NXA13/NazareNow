/**
 * The shell both pages share: the masthead, the navigation, and which page is showing.
 *
 * Everything that fetches or renders a figure lives in `Home` or `HowItWorks`. This file
 * decides only which of the two is on screen, so the redesign tickets that follow can rebuild
 * a page without touching the frame around it.
 */

import { Home } from './Home';
import { HowItWorks } from './HowItWorks';
import { useRoute, type Route } from './router';
import './App.css';

/** The two pages, in the order they are offered. `#/` rather than `#`: a browser leaves a bare
 * `#` in the address bar looking like a fragment that failed to find its target, and `#/`
 * reads as an address. Both resolve to the forecast. */
const PAGES: { route: Route; href: string; label: string }[] = [
  { route: 'forecast', href: '#/', label: 'Forecast' },
  { route: 'how-it-works', href: '#/how-it-works', label: 'How it works' },
];

export function App() {
  const route = useRoute();

  return (
    <main>
      <header>
        <h1>NazareNow</h1>
        <p className="tagline">When will Praia do Norte produce giant waves?</p>

        {/* Ordinary anchors. Following one, opening it in a new tab, copying it and pressing
            Back are the browser's own behaviour, and a click handler on a non-link would take
            all four away while looking identical in a screenshot. */}
        <nav aria-label="Pages">
          {PAGES.map((page) => (
            <a
              key={page.href}
              href={page.href}
              // For a reader who cannot see which link is lit. The styling that marks the
              // current page hangs off this attribute rather than beside it, so the two
              // cannot disagree.
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
