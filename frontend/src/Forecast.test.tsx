/**
 * The forecast range, driven through what a user sees and does.
 *
 * Same seam as App.test.tsx: the API is mocked at the network boundary and only visible
 * behaviour is asserted. Assertions target fixture values so none can pass by matching
 * static copy — a mistake this suite has shipped twice.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { ForecastRange } from './Forecast';
import { forecast } from './test/handlers';
import { server } from './test/server';

const QUIET = forecast.days[0]!;
const BIG = forecast.days[1]!;

describe('the forecast range', () => {
  it('marks the standout day so the overview can be scanned, not read', async () => {
    // Asserted through the rendered class, not by calling the helper: the agreed seam
    // is what a user sees. The scale is relative to the range on screen, so it works on
    // a flat summer week as well as on a winter one.
    render(<ForecastRange />);

    const quiet = await screen.findByRole('button', { name: new RegExp(QUIET.date) });
    const big = await screen.findByRole('button', { name: new RegExp(BIG.date) });

    expect(big.className).toContain('rank-leading');
    expect(quiet.className).toContain('rank-ordinary');
    // The middle tier is a real band, not decoration: a day at 43% of the peak must be
    // neither leading nor ordinary. Without this, widening either threshold to swallow
    // the tier passed every test.
    const easing = await screen.findByRole('button', { name: new RegExp(forecast.days[2]!.date) });
    expect(easing.className).toContain('rank-notable');
  });

  it('still marks a standout day when the whole range is small', async () => {
    // The real database is a flat summer week where every day is 0.6-1.2m. Absolute
    // thresholds put all nine in one bucket and distinguished nothing.
    const flat = {
      ...forecast,
      days: forecast.days.map((day, index) => ({
        ...day,
        peak_swell_height: { value: index === 1 ? 1.2 : 0.7, unit: 'm' },
      })),
    };
    server.use(http.get('*/api/conditions/forecast', () => HttpResponse.json(flat)));

    render(<ForecastRange />);

    const big = await screen.findByRole('button', { name: new RegExp(BIG.date) });
    const quiet = await screen.findByRole('button', { name: new RegExp(QUIET.date) });
    expect(big.className).toContain('rank-leading');
    expect(quiet.className).toContain('rank-ordinary');
  });

  it('names every summarised figure for a screen reader', async () => {
    // aria-label overrides the card's content, so anything it omits is lost entirely.
    render(<ForecastRange />);

    const day = await screen.findByRole('button', { name: new RegExp(BIG.date) });
    const label = day.getAttribute('aria-label') ?? '';
    expect(label).toContain(String(BIG.peak_swell_height.value));
    expect(label).toContain(String(BIG.swell_period_at_peak.value));
    expect(label).toContain('WNW');
    // The fix that added longest_swell_period did not guard it: deleting its clause
    // from the label passed every test.
    expect(label).toContain(String(BIG.longest_swell_period.value));
  });

  it('shows the day label and hours in order, marked as UTC', async () => {
    // Surviving mutants before this: dayLabel returning a constant, the hour rows
    // reversed, and the Time column frozen on the first hour.
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    const table = await screen.findByRole('table');

    // Both the caption and the Time column say UTC; either alone would do.
    expect(within(table).getAllByText(/UTC/).length).toBeGreaterThan(0);
    const times = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('rowheader')[0]?.textContent ?? '');
    expect(times[0]).toBe('00:00');
    expect(times[23]).toBe('23:00');
    expect([...times]).toEqual([...times].sort());
  });

  it('lists every day the forecast covers', async () => {
    render(<ForecastRange />);

    const days = await screen.findAllByRole('button', { name: /2026|Feb/i });
    expect(days).toHaveLength(forecast.days.length);
  });

  it('shows a quiet day rather than hiding it', async () => {
    // Omitting flat days would leave gaps a reader cannot tell from missing data, and
    // "nothing is coming" is a real answer to "when should I go".
    render(<ForecastRange />);

    const day = await screen.findByRole('button', { name: new RegExp(QUIET.date) });
    expect(within(day).getByText(String(QUIET.peak_swell_height.value))).toBeInTheDocument();
  });

  it('keeps height, period and direction distinguishable in the overview', async () => {
    render(<ForecastRange />);

    const day = await screen.findByRole('button', { name: new RegExp(BIG.date) });
    expect(within(day).getByText(String(BIG.peak_swell_height.value))).toBeInTheDocument();
    expect(within(day).getByText(String(BIG.swell_period_at_peak.value))).toBeInTheDocument();
    expect(within(day).getByText(/WNW/)).toBeInTheDocument();
  });

  it('opens a day to reveal its hours', async () => {
    render(<ForecastRange />);

    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    const table = await screen.findByRole('table');
    // 24 hours plus the header row.
    expect(within(table).getAllByRole('row')).toHaveLength(25);

    // Each hour carries its own values. Asserting a count of identical cells could not
    // tell this table from one rendering hour zero twenty-four times.
    const rows = within(table).getAllByRole('row').slice(1);
    for (const hour of [0, 7, 23]) {
      const cells = within(rows[hour]!).getAllByRole('cell');
      expect(cells[0]).toHaveTextContent(String(BIG.hours[hour]!.swell_height.value));
      expect(cells[1]).toHaveTextContent(String(BIG.hours[hour]!.swell_period.value));
      expect(cells[3]).toHaveTextContent(String(BIG.hours[hour]!.wind_speed.value));
    }
  });

  it('shows a different day when a different day is opened', async () => {
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(QUIET.date) }));

    // Read the swell cell of a specific row. Searching the whole table for a number
    // gives false matches — 8.65 is BIG's swell at 05:00 and also QUIET's period there.
    const table = await screen.findByRole('table');
    const row = within(table).getAllByRole('row')[6]!;
    const swellCell = within(row).getAllByRole('cell')[0]!;

    expect(swellCell).toHaveTextContent(String(QUIET.hours[5]!.swell_height.value));
    expect(swellCell).not.toHaveTextContent(String(BIG.hours[5]!.swell_height.value));
  });

  it('marks the open day as selected', async () => {
    // The commit that fixed the selection styling claimed this was asserted through the
    // rendered class. It was not: nothing referenced `selected` or aria-pressed, and
    // four mutants survived — the class never applied, always applied, and aria-pressed
    // pinned either way.
    render(<ForecastRange />);

    const big = await screen.findByRole('button', { name: new RegExp(BIG.date) });
    const quiet = await screen.findByRole('button', { name: new RegExp(QUIET.date) });
    expect(big).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(big);

    expect(big).toHaveAttribute('aria-pressed', 'true');
    expect(big.className).toContain('selected');
    expect(quiet).toHaveAttribute('aria-pressed', 'false');
    expect(quiet.className).not.toContain('selected');
  });

  it('closes the open day when it is clicked again', async () => {
    render(<ForecastRange />);

    const big = await screen.findByRole('button', { name: new RegExp(BIG.date) });
    await userEvent.click(big);
    expect(await screen.findByRole('table')).toBeInTheDocument();

    await userEvent.click(big);

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(big).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows a readable date on each day, not the raw ISO string', async () => {
    // Days are found by aria-label, which carries the ISO date — so the visible label
    // went unasserted, and dayLabel returning a constant survived every test.
    render(<ForecastRange />);

    const big = await screen.findByRole('button', { name: new RegExp(BIG.date) });
    expect(big).toHaveTextContent(/Fri 13 Feb|13 Feb|Feb 13/);
    expect(big).not.toHaveTextContent(BIG.date);
  });

  it('says how many days the forecast covers', async () => {
    render(<ForecastRange />);

    expect(
      await screen.findByRole('heading', { name: `The next ${forecast.days.length} days` }),
    ).toBeInTheDocument();
  });

  it('tells the user when the forecast cannot be loaded', async () => {
    server.use(
      http.get('*/api/conditions/forecast', () => new HttpResponse(null, { status: 503 })),
    );

    render(<ForecastRange />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/forecast/i);
  });
});
