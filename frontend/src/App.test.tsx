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

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from './App';
import { currentConditions, trackRecord } from './test/handlers';
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

  /**
   * The four tiles (#116).
   *
   * `/api/conditions/current` sends ten readings and the design shows four tiles, and the four
   * are not an arbitrary selection: they are **exactly the quantities a Go Call is gated on**.
   * That is the rule the spec settled, and it is what makes the row legible — the tile row is
   * what the call is decided on, at the size of a headline.
   *
   * The other six are not dropped, because a pipeline that went on fetching and storing figures
   * the site never shows would be worse than a short line. Each tile carries the rest of its own
   * wave field, small, and the two temperatures gate nothing so they take one quiet line.
   */
  describe('the four tiles', () => {
    /** The gated quantity each tile leads with, in the order the row shows them. */
    const GATED: [string, string][] = [
      ['significant-wave-height', 'Significant wave height'],
      ['swell-period', 'Swell period'],
      ['swell-direction', 'Swell direction'],
      ['wind-speed', 'Wind speed'],
    ];

    it('gives a tile to each gated quantity, and to nothing else', async () => {
      // Four, by name, rather than four by count. A row of the right length carrying the wrong
      // quantity reads perfectly and is a different instrument.
      render(<App />);
      await screen.findByTestId('tiles');

      const tiles = screen.getAllByTestId(/^tile-/);
      expect(tiles.map((tile) => tile.dataset.testid ?? tile.getAttribute('data-testid'))).toEqual(
        GATED.map(([slug]) => `tile-${slug}`),
      );
    });

    it.each(GATED)('leads the %s tile with that reading', async (slug, label) => {
      render(<App />);

      const tile = await screen.findByTestId(`tile-${slug}`);
      expect(within(tile).getByRole('group', { name: label })).toBeInTheDocument();
    });

    it('keeps the Combined Sea together on the height tile', async () => {
      // CONTEXT.md: the Combined Sea is the whole wave field and is described by Significant
      // Wave Height, so its period and direction belong to this tile and not to the Swell's.
      // Putting them anywhere else would invite reading a combined figure as a swell one.
      render(<App />);

      const tile = await screen.findByTestId('tile-significant-wave-height');
      expect(within(tile).getByRole('group', { name: 'Wave period' })).toBeInTheDocument();
      expect(within(tile).getByRole('group', { name: 'Wave direction' })).toBeInTheDocument();
    });

    it("keeps the Swell's own height visibly apart from the combined figure", async () => {
      // The one placement that carries a claim. Swell is only the travelled component and is
      // what the canyon amplifies; the Combined Sea includes locally raised wind waves. A
      // reader who takes the swell height for the significant wave height has misread the two
      // quantities CONTEXT.md is most careful to keep apart.
      render(<App />);

      const swellPeriod = await screen.findByTestId('tile-swell-period');
      const height = await screen.findByTestId('tile-significant-wave-height');

      expect(within(swellPeriod).getByRole('group', { name: 'Swell height' })).toBeInTheDocument();
      expect(within(height).queryByRole('group', { name: 'Swell height' })).toBeNull();
    });

    it('carries the wind bearing beside its speed', async () => {
      render(<App />);

      const tile = await screen.findByTestId('tile-wind-speed');
      expect(within(tile).getByRole('group', { name: 'Wind direction' })).toBeInTheDocument();
    });

    it('puts the two temperatures on one line under the tiles, gating nothing', async () => {
      // They were nearly declared unread and were not. One line, below the row, because a
      // temperature decides nothing about whether to travel and a tile would say it does.
      render(<App />);

      const line = await screen.findByTestId('temperatures');
      expect(within(line).getByRole('group', { name: 'Water temperature' })).toBeInTheDocument();
      expect(within(line).getByRole('group', { name: 'Air temperature' })).toBeInTheDocument();

      const tiles = await screen.findByTestId('tiles');
      expect(tiles.compareDocumentPosition(line)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    });

    it('states that the figures are modelled rather than measured, beside them', async () => {
      // The spec's rule: limits that qualify a number stay beside that number, and teaching
      // material moves. Nothing on this page is an observation — every figure is model output
      // at a grid point, and no buoy reading reaches the live system at all.
      render(<App />);

      expect(await screen.findByTestId('provenance')).toHaveTextContent(/modelled/i);
    });

    it('keeps that provenance out of the footer, where it was fine print', async () => {
      // #116: the provenance must be "no smaller, dimmer or later than the figures it
      // qualifies". It was the last element on the page, inside a `footer` styled a step down
      // the type scale and a step toward the muted tone — smaller, dimmer and later, all three
      // at once, which is precisely how a disclaimer becomes elegant grey fine print without
      // anybody deciding it should.
      render(<App />);

      const provenance = await screen.findByTestId('provenance');
      expect(provenance.closest('footer')).toBeNull();
    });

    it('puts the provenance with the tiles rather than at the bottom of the page', async () => {
      // "Later" is the half of that criterion a colour check cannot see. Beside the figures
      // means before the day list, not after everything.
      render(<App />);

      const provenance = await screen.findByTestId('provenance');
      const tiles = await screen.findByTestId('tiles');
      const days = await screen.findByRole('heading', { name: /^The next \d+ days$/ });

      expect(tiles.compareDocumentPosition(provenance)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      expect(provenance.compareDocumentPosition(days)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    });
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

  it('keeps the staleness warning above the verdict', async () => {
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
    const verdict = await screen.findByTestId('verdict');
    expect(warning.compareDocumentPosition(verdict)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
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

  describe('how often the printed range has held (#119)', () => {
    /**
     * #119 lists the range-runs-wide admission among the things that stay on the forecast page,
     * "attached to the figures they qualify". It was not on this page at all: the whole finding
     * lived on the reading page, under the tables that produced it, which left the verdict
     * printing a plausible range with nothing beside it saying how often a range like that has
     * held.
     *
     * The table stays on the reading page — that part is teaching. What belongs here is the one
     * sentence a reader needs before acting on the range above it.
     */
    /** The record with its coverage forced to a given share at every lead time, which is what
     * decides which way the admission reads. */
    function recordCovering(covered: number) {
      const range = trackRecord.range_calibration;
      return {
        ...trackRecord,
        range_calibration: {
          ...range,
          leads: range.leads.map((lead) => ({
            ...lead,
            all_hours: { ...lead.all_hours, covered },
          })),
        },
      };
    }

    async function admissionFor(covered: number) {
      server.use(http.get('*/api/track-record', () => HttpResponse.json(recordCovering(covered))));
      render(<App />);
      return screen.findByTestId('range-admission');
    }

    it('sits under the verdict and above the days, beside the range it qualifies', async () => {
      render(<App />);

      const admission = await screen.findByTestId('range-admission');
      const verdict = await screen.findByTestId('verdict');
      const days = await screen.findByRole('heading', { name: /^The next \d+ days$/ });

      expect(verdict.compareDocumentPosition(admission)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      expect(admission.compareDocumentPosition(days)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    });

    it('says so when the range has held less often than it claims', async () => {
      // The dangerous direction, and the reason this cannot be a component that only speaks up
      // when the news is good: a range holding less often than it claims makes the system look
      // surer than it is, which is the failure mode that costs someone a flight.
      const admission = await admissionFor(0.7);

      expect(admission).toHaveTextContent(/held less often than it claims/i);
      expect(admission).toHaveTextContent(/optimistic edge of the doubt/i);
    });

    it('says so when it runs wider than the outcomes justify', async () => {
      const admission = await admissionFor(0.98);

      expect(admission).toHaveTextContent(/wider than the outcomes justify/i);
      // Named as the forgiving direction rather than left to read as a fault of the same size.
      expect(admission).toHaveTextContent(/forgiving direction/i);
    });

    it('refuses a single answer when the table disagrees with itself', async () => {
      const range = trackRecord.range_calibration;
      server.use(
        http.get('*/api/track-record', () =>
          HttpResponse.json({
            ...trackRecord,
            range_calibration: {
              ...range,
              leads: range.leads.map((lead, index) => ({
                ...lead,
                all_hours: { ...lead.all_hours, covered: index === 0 ? 0.7 : 0.98 },
              })),
            },
          }),
        ),
      );
      render(<App />);

      const admission = await screen.findByTestId('range-admission');
      expect(admission).toHaveTextContent(/depends on how far ahead it looks/i);
    });

    it('states the share the range claims, from the record rather than a literal', async () => {
      const admission = await admissionFor(0.9);
      expect(admission).toHaveTextContent(
        `${Math.round(trackRecord.range_calibration.claimed * 100)}%`,
      );
    });

    it('renders nothing at all until the record has arrived', async () => {
      // Unlike the track-record line lower down, this sits directly under a figure. A
      // placeholder here would read as a qualification of that figure rather than as something
      // still on its way.
      server.use(http.get('*/api/track-record', () => new HttpResponse(null, { status: 503 })));

      render(<App />);

      await screen.findByTestId('verdict');
      expect(screen.queryByTestId('range-admission')).toBeNull();
    });
  });

  describe('the line of track record (#119)', () => {
    /**
     * The debt #113 took on knowingly. It removed an assertion that the track record was *on*
     * the page rather than behind a link, on the reasoning that a track record nobody navigates
     * to is a limitation nobody reads, and left a link in its place for exactly one ticket.
     *
     * What makes this the strong form again is that the line carries figures. A link saying
     * "how well these calls have done" asks a reader to go and find out; a line saying a Go Call
     * landed on 12 of 13 confirmed days, and that at worst 94% of them would have been wasted,
     * has already told them.
     */
    const TIER = trackRecord.held_out.go_call;

    /** The line once the record has actually arrived.
     *
     * `findByTestId` alone is not enough and the difference is the point: the line renders
     * immediately, carrying only the link, so that a failed or slow track record never reads as
     * the forecast having failed. A test that stopped at the test id would assert against that
     * placeholder and pass while the figures never arrived. The node itself is stable — both
     * branches return the same element in the same position, so React reconciles rather than
     * replaces it. */
    async function loadedLine() {
      const line = await screen.findByTestId('track-record-line');
      await waitFor(() => expect(line).toHaveTextContent(/never saw/i));
      return line;
    }

    it('carries figures, not just an invitation to go and look', async () => {
      render(<App />);

      const line = await loadedLine();
      expect(line).toHaveTextContent(String(TIER.gold_days_called));
      expect(line).toHaveTextContent(String(TIER.gold_days_in_panel));
      expect(line).toHaveTextContent(String(trackRecord.held_out.big_wave_seasons));
    });

    it('states what the calls cost as well as what they caught', async () => {
      // A line carrying recall alone is the flattering half of a pair, and this project exists
      // to avoid exactly that. Both numbers or neither.
      render(<App />);

      const line = await loadedLine();
      const waste = `${Math.round(TIER.wasted_upper_bound * 100)}%`;

      expect(line).toHaveTextContent(waste);
      expect(line).toHaveTextContent(/wasted/i);
    });

    it('names the counterweight the waste figure needs rather than printing it bare', async () => {
      // `TierRecord` requires `wasted_upper_bound` and `delivered` to travel together: waste is
      // scored against ratified giant days, a bar so high that a rule flagging nothing but
      // excellent days still reads as mostly wasted. One line cannot carry both without becoming
      // a paragraph, so it has to say the counterweight exists and where it is. Printing the
      // waste figure alone would be the misreading that rule was written to prevent.
      render(<App />);

      const line = await loadedLine();
      expect(line).toHaveTextContent(/ratified days only/i);
      expect(within(line).getByRole('link')).toHaveAttribute('href', '#/how-it-works');
    });

    it('measures on the seasons the thresholds never saw, not on the whole record', async () => {
      // The held-out panel is the one that answers "would this have helped me". The full record
      // partly covers the seasons the thresholds were chosen on, and a line quoting it would be
      // quoting the system's performance on its own training material.
      render(<App />);

      const line = await loadedLine();
      expect(line).toHaveTextContent(/never saw/i);
      expect(line.textContent).not.toContain(
        String(trackRecord.full_record.go_call.gold_days_in_panel),
      );
    });

    it('still links out, and says nothing it cannot support, when the record will not load', async () => {
      // The calls above this line do not depend on the track record, so a failure here must not
      // read as the forecast having failed. What it must not do is keep the sentence and drop
      // the figures, which would leave a claim with nothing behind it.
      server.use(http.get('*/api/track-record', () => new HttpResponse(null, { status: 503 })));

      render(<App />);

      const line = await screen.findByTestId('track-record-line');
      expect(within(line).getByRole('link')).toHaveAttribute('href', '#/how-it-works');
      expect(line.textContent).not.toMatch(/wasted|confirmed giant/i);
      expect(screen.queryByRole('alert')).toBeNull();
    });
  });

  it('sends a reader to the track record from the forecast, in one link', async () => {
    // This assertion used to read "carries the track record on the page, not behind a link",
    // and the reasoning behind it was that a track record nobody navigates to is a limitation
    // nobody reads. v2 moves it to its own page, so that reasoning now has to be carried by
    // something else: the link itself, which is why its presence is asserted here rather than
    // left to the nav's own test.
    //
    // **#119 has now restored the strong form**, in the block below this one: a line of track
    // record on the home page, carrying figures rather than only an invitation. This test keeps
    // its narrower job — that the link itself exists and points at the right address.
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
