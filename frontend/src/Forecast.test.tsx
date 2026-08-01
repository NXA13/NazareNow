/**
 * The forecast range, driven through what a user sees and does.
 *
 * Same seam as App.test.tsx: the API is mocked at the network boundary and only visible
 * behaviour is asserted. Assertions target fixture values so none can pass by matching
 * static copy — a mistake this suite has shipped twice.
 */

import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { ForecastRange } from './Forecast';
import { compassPoint } from './format';
import { dayFrom, forecast } from './test/handlers';
import { server } from './test/server';

const QUIET = forecast.days[0]!;
const BIG = forecast.days[1]!;
const BIG_CALL = BIG.call!;

/** Serve a forecast whose days are the ones given, leaving the rest of it alone. */
function serveDays(days: (typeof forecast)['days']) {
  server.use(http.get('*/api/conditions/forecast', () => HttpResponse.json({ ...forecast, days })));
}

describe('calls', () => {
  it('shows each status distinguishably, with the right label on each', async () => {
    // Asserting only that three labels differ let Go and Watch swap places — a Go day
    // reading "Watch — something may be forming, do not book yet". Which label belongs
    // to which status is the whole point, so each is pinned by name.
    render(<ForecastRange />);

    const badges = await Promise.all(
      forecast.days.map((day) => screen.findByTestId(`call-${day.date}`)),
    );

    expect(badges.map((b) => b.className)).toEqual([
      'call call-confirmed',
      'call call-go',
      'call call-watch',
    ]);
    expect(badges.map((b) => b.textContent)).toEqual(['Confirmed', 'Go', 'Watch']);
  });

  it('shows a day judged not worth travelling for, and says so', async () => {
    // The `none` status had no fixture anywhere, so nothing rendered it and nothing
    // asserted it — the one status a real quiet week produces on every single day.
    const quiet = dayFrom('2026-02-15', 1.1, 7, 250, 'none', 6);
    serveDays([quiet]);

    render(<ForecastRange />);

    const badge = await screen.findByTestId(`call-${quiet.date}`);
    expect(badge).toHaveTextContent('No call');
    expect(badge.className).toBe('call call-none');

    await userEvent.click(screen.getByRole('button', { name: new RegExp(quiet.date) }));
    expect(await screen.findByRole('note')).toHaveTextContent(/not a day to travel for/i);
  });

  it('distinguishes a day nothing has judged from one judged not worth travelling for', async () => {
    // A gap in the call record is not a verdict. Rendering it as "No call" would report
    // an absence of data as advice.
    const unjudged = dayFrom('2026-02-16', 6.4, 15, 290, null);
    serveDays([unjudged]);

    render(<ForecastRange />);

    const badge = await screen.findByTestId(`call-${unjudged.date}`);
    expect(badge).toHaveTextContent('Not judged');
    expect(badge.className).toBe('call call-unjudged');

    await userEvent.click(screen.getByRole('button', { name: new RegExp(unjudged.date) }));
    const note = await screen.findByRole('note');
    expect(note).toHaveTextContent(/no pipeline run has assessed this day/i);
    // No lead time, no reasons and no predicted height: there is no call to report them.
    expect(note).not.toHaveTextContent(/days ahead/i);
    expect(note).not.toHaveTextContent(/predicted significant wave height/i);
  });

  it('keeps the hourly detail for a day nothing has judged', async () => {
    // The hours are real even when the call record is empty; dropping them would throw
    // away what the forecast range delivers over a missing call.
    const unjudged = dayFrom('2026-02-16', 6.4, 15, 290, null);
    serveDays([unjudged]);

    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(unjudged.date) }));

    expect(within(await screen.findByRole('table')).getAllByRole('row')).toHaveLength(25);
  });

  it('says the predicted height is the offshore figure carried through unchanged', async () => {
    // The Heuristic Baseline applies no amplification, so "predicted" without that
    // sentence invites a reader to think the canyon has been modelled. It has not been.
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    expect(await screen.findByRole('note')).toHaveTextContent(/carried through unchanged/i);
  });

  it('describes a Go Call as worth booking and a Watch as not yet', async () => {
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    expect(await screen.findByRole('note')).toHaveTextContent(/worth booking/i);

    const easing = forecast.days[2]!;
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(easing.date) }));
    const note = await screen.findByRole('note');
    expect(note).toHaveTextContent(/do not book yet/i);
    expect(note).not.toHaveTextContent(/worth booking/i);
  });

  it('does not claim the forecast has converged', async () => {
    // Nothing measures convergence. ADR 0003 has the tiers driven by Model Spread, which
    // ticket #8 introduces; until then a claim of convergence is an invented assurance.
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    expect(await screen.findByRole('note')).not.toHaveTextContent(/converged/i);
  });

  it('explains why a day got its call, and how far ahead', async () => {
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    const note = await screen.findByRole('note');

    for (const reason of BIG_CALL.reasons) {
      expect(note).toHaveTextContent(reason);
    }
    expect(note).toHaveTextContent(`${BIG_CALL.lead_time_days} days ahead`);
  });

  it('shows the predicted wave height and says it is not the face height', async () => {
    // CONTEXT.md calls this distinction load-bearing: the canyon's amplification applies
    // to the face a surfer rides, not to the instrument's measure of the sea.
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    const note = await screen.findByRole('note');

    expect(note).toHaveTextContent(String(BIG_CALL.predicted_significant_wave_height.value));
    expect(note).toHaveTextContent(/not the height of the wave face/i);
  });

  it('warns that the thresholds are not calibrated', async () => {
    render(<ForecastRange />);

    expect(await screen.findByRole('status')).toHaveTextContent(/rule of thumb/i);
  });

  it('drops the warning once the model is calibrated', async () => {
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, calibrated: true }),
      ),
    );

    render(<ForecastRange />);

    await screen.findByTestId(`call-${BIG.date}`);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

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
    // The middle tier is a real band, not decoration: a day at 70% of the peak must be
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

  it('names the same calendar day the backend grouped, east of UTC+12', async () => {
    // The label was built from `${date}T12:00:00Z`, so a reader at UTC+13 saw noon UTC
    // land at 01:00 the *following* day and the card named a date the forecast never
    // contained (#25). Auckland in February is UTC+13.
    const day = dayFrom('2026-02-16', 4.2, 15, 298, 'go', 4);
    serveDays([day]);
    process.env.TZ = 'Pacific/Auckland';

    render(<ForecastRange />);

    // 2026-02-16 is a Monday. Pinned as a literal rather than derived from a Date, which
    // would reproduce whatever the code does and agree with it by construction.
    const label = await screen.findByTestId(`day-label-${day.date}`);
    expect(label.textContent).toContain('16');
    expect(label.textContent).toContain('Mon');
  });

  it('reads a screen reader the same digits the card displays', async () => {
    // The label interpolated the raw reading while the visible card ran it through
    // formatValue, so whenever a source carried more than two decimals the two disagreed
    // — and since aria-label *overrides* the card's content, a screen reader user got the
    // long number and no way to see the short one (#25).
    // The summary readings are overridden directly rather than passed through `dayFrom`,
    // which rounds every value it generates to 2dp — so a fixture built through it cannot
    // carry the extra decimals this test is about, and the first version of this test
    // passed with the bug still in the code. The backend applies no rounding of its own:
    // `Reading.value` is a float and the store keeps whatever the provider sent.
    const precise = {
      ...dayFrom('2026-02-16', 4.2, 15, 298, 'go', 4),
      peak_swell_height: { value: 4.23456, unit: 'm' },
      swell_period_at_peak: { value: 15.6789, unit: 's' },
      longest_swell_period: { value: 16.98765, unit: 's' },
    };
    serveDays([precise]);

    render(<ForecastRange />);

    const day = await screen.findByRole('button', { name: new RegExp(precise.date) });
    const label = day.getAttribute('aria-label') ?? '';

    expect(label).toContain('4.23');
    expect(label).not.toContain('4.23456');
    expect(label).toContain('15.68');
    expect(label).not.toContain('15.6789');
    expect(label).not.toContain('16.98765');
    // And the label agrees with what is on screen, which is the actual requirement.
    expect(label).toContain(
      within(day).getByTestId(`day-peak-${precise.date}`).textContent!.trim(),
    );
  });

  it('shows the day label and hours in order, marked as UTC', async () => {
    // Surviving mutants before this: dayLabel returning a constant, the hour rows
    // reversed, and the Time column frozen on the first hour.
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    const table = await screen.findByRole('table');

    // Both the caption and the Time column say UTC; either alone would do.
    expect(within(table).getAllByText(/UTC/).length).toBeGreaterThan(0);
    // The caption carries the same readable date as the tile; the raw ISO form survived.
    expect(table.querySelector('caption')?.textContent).toMatch(/[A-Za-z]{3}/);
    expect(table.querySelector('caption')?.textContent).not.toContain(BIG.date);
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
      const reading = BIG.hours[hour]!;
      expect(cells[0]).toHaveTextContent(
        `${reading.swell_height.value}${reading.swell_height.unit}`,
      );
      expect(cells[1]).toHaveTextContent(
        `${reading.swell_period.value}${reading.swell_period.unit}`,
      );
      // Cell 2 is the direction column, previously skipped: freezing it, or rendering
      // wind direction in it, passed every test.
      expect(cells[2]).toHaveTextContent(compassPoint(reading.swell_direction.value));
      expect(cells[3]).toHaveTextContent(`${reading.wind_speed.value}${reading.wind_speed.unit}`);
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
    // Days are found by aria-label, which carries the ISO date, so the visible label was
    // unasserted and dayLabel returning a constant survived. A regex matching one
    // expected label is not enough either — a constant satisfies it. Each day must
    // render its own distinct label.
    render(<ForecastRange />);

    const labels = await Promise.all(
      forecast.days.map(async (day) => {
        const tile = await screen.findByRole('button', { name: new RegExp(day.date) });
        return within(tile).getByTestId(`day-label-${day.date}`).textContent ?? '';
      }),
    );

    expect(new Set(labels).size).toBe(forecast.days.length);
    for (const [index, label] of labels.entries()) {
      expect(label).not.toContain(forecast.days[index]!.date);
      // A month name, not just digits. Requiring only distinctness let "13" and
      // "20260213" pass a test whose name promises a readable date.
      expect(label).toMatch(/[A-Za-z]{3}/);
      expect(label).toMatch(/\d/);
    }
    expect(labels[1]).toMatch(/13/);
  });

  it('says how many days the forecast covers', async () => {
    render(<ForecastRange />);

    // Two forecasts of different lengths. With one fixture, a heading hardcoded to
    // "The next 3 days" passed whether the expectation was a literal or derived — the
    // fixture was what made it blind, not the expectation.
    expect(await screen.findByRole('heading', { name: 'The next 3 days' })).toBeInTheDocument();

    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, days: forecast.days.slice(0, 2) }),
      ),
    );
    cleanup();
    render(<ForecastRange />);

    expect(await screen.findByRole('heading', { name: 'The next 2 days' })).toBeInTheDocument();
  });

  it('tells the user when the forecast cannot be loaded', async () => {
    server.use(
      http.get('*/api/conditions/forecast', () => new HttpResponse(null, { status: 503 })),
    );

    render(<ForecastRange />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/forecast/i);
  });
});
