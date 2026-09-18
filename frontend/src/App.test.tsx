/**
 * Tests for the interface, driven through what a user actually sees.
 *
 * This is one of the project's two agreed test seams. The API is mocked at the network
 * boundary; component internals, state management and styling are not asserted, so the
 * implementation behind these behaviours can be rewritten freely.
 *
 * Assertions target values imported from the fixtures rather than text matched loosely.
 * Two tests have already shipped here that asserted nothing: one matched the page's own
 * static subtitle, another matched the static word "Observed" while the date formatter
 * was broken. Every assertion below must fail if the API's value stops being rendered.
 *
 * **The one carve-out, and why it is not a hole.** The navigation tests below assert structure
 * rather than values — an address, a link's target, which page is marked current — and no API
 * value can make those fail. The rule above exists for a *figure* whose disappearance a test
 * would sleep through, which is what both of the tests it names were. A test that a page is
 * still reachable has no figure to sleep through, and the alternative to writing it is not
 * writing it: that is how the track record once came to be removed from the page with the
 * whole suite green.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from './App';
import { currentConditions } from './test/handlers';
import { server } from './test/server';

/** Find the labelled block for one reading, e.g. "Swell height". */
async function reading(label: string) {
  return within(await screen.findByRole('group', { name: new RegExp(`^${label}$`, 'i') }));
}

/** Every reading the API returns. A test below pins this list to the API type, so a
 * reading cannot be added to the contract without also being displayed and asserted. */
const READINGS: [string, keyof typeof currentConditions][] = [
  ['Swell height', 'swell_height'],
  ['Swell period', 'swell_period'],
  ['Swell direction', 'swell_direction'],
  ['Significant wave height', 'significant_wave_height'],
  ['Wave period', 'wave_period'],
  ['Wave direction', 'wave_direction'],
  ['Wind speed', 'wind_speed'],
  ['Wind direction', 'wind_direction'],
  ['Air temperature', 'air_temperature'],
  ['Water temperature', 'water_temperature'],
];

/** Fields describing the observation rather than being readings. `stale` belongs here:
 * it is a judgement about the run's age, surfaced as a warning rather than a value. */
const METADATA = [
  'observed_at',
  'fetched_at',
  'latitude',
  'longitude',
  'stale',
  'stale_after_hours',
];

describe('current conditions', () => {
  it('covers every reading the API returns', () => {
    // Without this, READINGS is just a hand-written list: an eleventh field could be
    // added to the API and the fixture and still pass 14 of 14.
    const fromApi = Object.keys(currentConditions).filter((key) => !METADATA.includes(key));
    const covered = READINGS.map(([, key]) => key as string);

    expect(covered.sort()).toEqual(fromApi.sort());
  });

  it.each(READINGS)('shows %s with its unit', async (label, key) => {
    const expected = currentConditions[key] as { value: number; unit: string };

    render(<App />);

    const block = await reading(label);
    expect(block.getByText(String(expected.value))).toBeInTheDocument();
    expect(block.getByText(expected.unit)).toBeInTheDocument();
  });

  it('shows directions as a compass bearing as well as degrees', async () => {
    // 298 degrees is west-north-west; 115 is east-south-east. A reader should not have
    // to know the convention to understand where the swell is coming from.
    render(<App />);

    expect((await reading('Swell direction')).getByText('WNW')).toBeInTheDocument();
    expect((await reading('Wind direction')).getByText('ESE')).toBeInTheDocument();
  });

  it('shows when the data was observed and when it was fetched', async () => {
    // Timezone is pinned to UTC in vite.config.ts, so these are deterministic. The
    // fixture is observed at 09:00 and fetched at 09:04 — asserting both proves the
    // formatter ran and that the two timestamps are not being conflated.
    render(<App />);

    const freshness = await screen.findByTestId('freshness');
    expect(freshness).toHaveTextContent(/observed/i);
    expect(freshness).toHaveTextContent(/09:00/);
    expect(freshness).toHaveTextContent(/09:04/);
    expect(freshness).toHaveTextContent(/13/);
  });

  it('warns prominently when the data is stale', async () => {
    // ADR 0005 promises the site stays up and honest when the provider is unreachable.
    // The warning is an alert and sits above the readings, because someone deciding
    // whether to book a flight must learn the data is old before they read the data.
    server.use(
      http.get('*/api/conditions/current', () =>
        HttpResponse.json({ ...currentConditions, stale: true }),
      ),
    );

    render(<App />);

    const warning = await screen.findByRole('alert');
    expect(warning).toHaveTextContent(/out of date/i);
    expect(warning).toHaveTextContent(/history, not advice/i);
    // The duration comes from the backend, not from a literal typed into the page. It was
    // "at least six hours" here while a docstring claimed the number was single-sourced,
    // so a change of cadence would have left this sentence quietly untrue.
    expect(warning).toHaveTextContent(`${currentConditions.stale_after_hours} hours`);

    // Above the readings, not after them: a warning below the numbers is read second.
    const swell = screen.getByRole('group', { name: 'Swell height' });
    expect(warning.compareDocumentPosition(swell)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('keeps the staleness warning above the earliest date worth acting on', async () => {
    // #86's third caution, and the shape of the defect #25 was filed about. The forecast
    // section now opens with a confident sentence telling a reader what to book; rendered
    // above the banner it would be advice given before the disclosure that it is history.
    // Nothing but document order enforces this, and nothing but this test reads it.
    server.use(
      http.get('*/api/conditions/current', () =>
        HttpResponse.json({ ...currentConditions, stale: true }),
      ),
    );

    render(<App />);

    const warning = await screen.findByRole('alert');
    const earliest = await screen.findByTestId('earliest-call');
    expect(warning.compareDocumentPosition(earliest)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('shows no staleness warning when the data is current', async () => {
    // The warning must be driven by the flag, not always rendered. A permanently visible
    // "out of date" banner is worse than none: it trains the reader to ignore it.
    render(<App />);

    await screen.findByRole('group', { name: 'Swell height' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not decide staleness for itself', async () => {
    // The backend owns "too old to trust" — ADR 0005 makes this layer a reader, and an
    // earlier version of this codebase reimplemented domain thresholds in the presentation
    // layer and got them wrong. A fetched_at from 2019 with stale: false must stay quiet.
    server.use(
      http.get('*/api/conditions/current', () =>
        HttpResponse.json({
          ...currentConditions,
          fetched_at: '2019-01-01T00:00:00+00:00',
          stale: false,
        }),
      ),
    );

    render(<App />);

    await screen.findByRole('group', { name: 'Swell height' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not claim any reading was measured', async () => {
    // The page said "Swell and sea measured at 39.54°N, 9.21°W — roughly 15km offshore,
    // near the head of the Nazaré Canyon". Nothing on it is an observation: every figure
    // is Open-Meteo model output at a grid point, and no buoy reading reaches the live
    // system — Monican02's record lives only in analysis/, for a model not yet built.
    // Describing a modelled figure as measured invites a reader to trust it further than
    // it deserves. Nothing asserted this wording, so the claim went unguarded.
    render(<App />);

    const provenance = await screen.findByTestId('provenance');
    expect(provenance).toHaveTextContent(/modelled/i);
    expect(provenance).toHaveTextContent(/not measured/i);
    expect(provenance).not.toHaveTextContent(/sea measured at/i);
  });

  it('says outright that no buoy reading reaches this page', async () => {
    // The other half of the same disclosure, and the half nothing held. "Modelled, not
    // measured" tells a reader the figure was computed; this tells them no instrument is
    // involved anywhere in the live system, which is the fact that makes the first one
    // permanent rather than a stage the project will grow out of. Deleting the sentence
    // passed every test.
    render(<App />);

    const provenance = await screen.findByTestId('provenance');

    expect(provenance).toHaveTextContent(/no buoy reading reaches this page/i);
    // And that wind is not even from the same grid point as the sea.
    expect(provenance).toHaveTextContent(/nearest land forecast cell/i);
  });

  it('places the site west of Greenwich rather than negating its own hemisphere', async () => {
    // The bearing letter is written into the copy and the number is taken absolute, so
    // dropping the `Math.abs` renders "−9.21°W" — a coordinate that reads as both west and
    // negative, which is either the wrong side of the meridian or nonsense. Nothing looked
    // at the number at all.
    render(<App />);

    const provenance = await screen.findByTestId('provenance');

    expect(provenance).toHaveTextContent(`${Math.abs(currentConditions.longitude).toFixed(2)}°W`);
    expect(provenance.textContent).not.toMatch(/[−-]\d+\.\d+°W/);
  });

  it('exposes the raw timestamps in machine-readable form', async () => {
    render(<App />);

    const freshness = await screen.findByTestId('freshness');
    const times = within(freshness).getAllByText(/\d{2}:\d{2}/);
    expect(times[0]).toHaveAttribute('datetime', currentConditions.observed_at);
  });

  it('sends a reader to the track record from the forecast, in one link', async () => {
    // This assertion used to read "carries the track record on the page, not behind a link",
    // and the reasoning behind it was that a track record nobody navigates to is a limitation
    // nobody reads. v2 moves it to its own page, so that reasoning now has to be carried by
    // something else: the link itself, which is why its presence is asserted here rather than
    // left to the nav's own test.
    //
    // The guarantee this test makes is weaker than the one it replaces, and deliberately so
    // for exactly one ticket. #119 restores the strong form — a line of track record on the
    // home page, and every limit that qualifies a number kept beside that number — and the
    // assertions that pin it belong with that work rather than here.
    render(<App />);

    const link = await screen.findByRole('link', { name: /how it works/i });
    expect(link).toHaveAttribute('href', '#/how-it-works');

    // The forecast is on this page and stays on it. Awaited separately: the sections fetch
    // independently, which is the point — a failure in one costs that section and not the
    // others — so they do not arrive together.
    expect(await screen.findByRole('heading', { name: /the next \d+ days/i })).toBeInTheDocument();
  });

  it('tells the user when no conditions have been ingested yet', async () => {
    // The backend returns 503 rather than zeros when its store is empty. A flat, calm
    // ocean is a plausible-looking lie; this must read as a fault.
    server.use(http.get('*/api/conditions/current', () => new HttpResponse(null, { status: 503 })));

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i);
    expect(screen.queryByRole('group', { name: /swell height/i })).toBeNull();
  });
});

/**
 * Two pages, and the address bar that decides which one a reader is looking at.
 *
 * Driven the way a reader drives it — following a link, pressing Back, opening an address
 * directly — rather than by calling the router. The router is an implementation detail and is
 * free to be rewritten; what is asserted here is that both pages are reachable, that an
 * address survives a reload, and that neither of those depends on JavaScript having decided to
 * intercept a click.
 */
describe('navigation', () => {
  /** Leave the address bar as the next test expects to find it. jsdom keeps one `window`
   * across a file, so a hash left behind by one test is the next test's starting page. */
  afterEach(() => {
    window.location.hash = '';
  });

  it('opens on the forecast', async () => {
    render(<App />);

    expect(await screen.findByRole('heading', { name: /the next \d+ days/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /track record/i })).toBeNull();
  });

  it('shows the track record at its own address, opened directly', async () => {
    // What a bookmark, a shared link or a reload does. It must not depend on the click that
    // would normally have got a reader here.
    window.location.hash = '#/how-it-works';

    render(<App />);

    expect(await screen.findByRole('heading', { name: /track record/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /the next \d+ days/i })).toBeNull();
  });

  it('shows the forecast at an address nobody recognises', async () => {
    // A hash route has no server to answer with a 404, so the only choice is which page a
    // wrong address lands on. A blank one is the failure this asserts against.
    window.location.hash = '#/nowhere';

    render(<App />);

    expect(await screen.findByRole('heading', { name: /the next \d+ days/i })).toBeInTheDocument();
  });

  it('follows a link to the track record and back again', async () => {
    render(<App />);
    await screen.findByRole('heading', { name: /the next \d+ days/i });

    await userEvent.click(screen.getByRole('link', { name: /how it works/i }));
    expect(await screen.findByRole('heading', { name: /track record/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('link', { name: /forecast/i }));
    expect(await screen.findByRole('heading', { name: /the next \d+ days/i })).toBeInTheDocument();
  });

  it('goes back to the forecast when the reader presses Back', async () => {
    // The whole reason this is a router and not two `useState` flags. A page swapped by state
    // alone leaves the address bar behind, and the Back button then takes a reader out of the
    // site altogether — to whatever they were reading before they arrived.
    render(<App />);
    await screen.findByRole('heading', { name: /the next \d+ days/i });

    await userEvent.click(screen.getByRole('link', { name: /how it works/i }));
    await screen.findByRole('heading', { name: /track record/i });

    window.history.back();

    expect(await screen.findByRole('heading', { name: /the next \d+ days/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /track record/i })).toBeNull();
  });

  it('navigates with real links rather than with click handlers', async () => {
    // The argument for anchors is written where the anchors are, in App.tsx. This is the
    // assertion that keeps it true — and it is worth one, because a click handler passes every
    // other test in this block and looks identical in a screenshot.
    render(<App />);

    for (const [name, href] of [
      [/forecast/i, '#/'],
      [/how it works/i, '#/how-it-works'],
    ] as const) {
      expect(await screen.findByRole('link', { name })).toHaveAttribute('href', href);
    }
  });

  it('marks the page being read, for a reader who cannot see which link is lit', async () => {
    window.location.hash = '#/how-it-works';

    render(<App />);

    expect(await screen.findByRole('link', { name: /how it works/i })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: /forecast/i })).not.toHaveAttribute('aria-current');
  });
});
