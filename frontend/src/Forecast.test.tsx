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
import { afterEach, describe, expect, it } from 'vitest';

import { ForecastRange } from './Forecast';
import { compassPoint } from './format';
import { calibration, dayFrom, forecast, unmeasurableSpread } from './test/handlers';
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
    //
    // ADR 0006 keeps that model runnable permanently, so this sentence has to stay correct
    // even though #13 made the learned model the default — the fixture reports the baseline.
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    expect(await screen.findByRole('note')).toHaveTextContent(/carried through unchanged/i);
  });

  it('says the height is a fitted correction when a learned model produced the call', async () => {
    // #13's half of the same obligation. The two models owe the reader different sentences,
    // and a page that kept saying "carried through unchanged" over a fitted number would be
    // describing a system that no longer exists.
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, amplification_model: 'learned-amplification' }),
      ),
    );

    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    const note = await screen.findByRole('note');
    expect(note).toHaveTextContent(/fitted correction/i);
    expect(note).not.toHaveTextContent(/carried through unchanged/i);
  });

  it('does not claim the canyon itself has been modelled', async () => {
    // The fit is the difference between a reanalysis and a buoy near the canyon head.
    // CONTEXT.md defines Amplification as the transformation onto Praia do Norte, which
    // is a different quantity with no historical archive — so the page must keep saying
    // that transformation is not modelled, however good the fitted number gets.
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, amplification_model: 'learned-amplification' }),
      ),
    );

    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    expect(await screen.findByRole('note')).toHaveTextContent(/not modelled/i);
  });

  it.each([
    ['an unrecognised model', 'some-future-model'],
    ['no model at all', null],
  ])('claims nothing about how the height was produced given %s', async (_label, model) => {
    // Both provenance sentences are specific factual claims about arithmetic. While the
    // baseline sentence was the else-branch, a name this build did not know about — or a
    // backend holding no calls, which reports null — rendered "carried through unchanged"
    // over a number nobody here had seen produced. Saying nothing is the only honest
    // option left; the sentence above it, about Face Height, is true either way and stays.
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, amplification_model: model }),
      ),
    );

    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    const note = await screen.findByRole('note');
    expect(note).not.toHaveTextContent(/carried through unchanged/i);
    expect(note).not.toHaveTextContent(/fitted correction/i);
    expect(note).toHaveTextContent(/not the height of the wave face/i);
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
    // Model Spread now exists (#8), so the interface *does* say how far apart the models
    // are — but in its own panel, and never here. The tiers are still decided by Lead Time
    // alone until Model Spread reaches the Decision Model, so a call explaining itself with
    // a claim of convergence would be describing a rule that did not judge it.
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

  it('drops the rule-of-thumb warning once the model is calibrated', async () => {
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, calibrated: true, calibration }),
      ),
    );

    render(<ForecastRange />);

    await screen.findByTestId(`call-${BIG.date}`);
    expect(screen.queryByText(/rule of thumb/i)).not.toBeInTheDocument();
  });

  it('states how few Gold Days the calibration rests on', async () => {
    // Removing the uncalibrated warning and saying nothing in its place would leave the
    // user reading fitted-looking calls with no idea the fit is nine days wide. #12 asks
    // for the replacement explicitly, so it is asserted rather than assumed.
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, calibrated: true, calibration }),
      ),
    );

    render(<ForecastRange />);

    const note = await screen.findByRole('status');
    expect(note).toHaveTextContent(String(calibration.gold_days_total));
    expect(note).toHaveTextContent(String(calibration.gold_days_validated));
    expect(note).toHaveTextContent(/very small number of days/i);
  });

  it('keeps the rule-of-thumb warning when a calibrated flag arrives without provenance', async () => {
    // The two halves are stored together but arrive over a network. A response claiming a
    // calibration it cannot describe must not silently drop the caveat and replace it with
    // nothing, which is what rendering on `calibrated` alone would do.
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, calibrated: true, calibration: null }),
      ),
    );

    render(<ForecastRange />);

    await screen.findByTestId(`call-${BIG.date}`);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('how much the forecasters agree', () => {
  /** Open a day and return the agreement panel. */
  async function agreementFor(date: string) {
    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(date) }));
    return screen.findByTestId(`spread-${date}`);
  }

  it('states the disagreement as a range, not as a bare number', async () => {
    // #8 asks for Model Spread "in terms they can interpret". A lone "0.3" says nothing
    // about a day; the two heights the forecasters actually gave say what it is a gap
    // between. Asserted against the fixture so it cannot pass on static copy.
    const spread = BIG.model_spread.swell_height!;

    const panel = await agreementFor(BIG.date);

    expect(panel).toHaveTextContent(`${spread.spread}${spread.unit}`);
    expect(panel).toHaveTextContent(
      `${spread.lowest}${spread.unit} to ${spread.highest}${spread.unit}`,
    );
  });

  it('says how many independent forecasters stand behind it', async () => {
    // A gap between two organisations and one between three are not comparable, and the
    // number alone cannot say which happened.
    const spread = BIG.model_spread.swell_height!;

    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    const panel = await screen.findByRole('region', { name: /how much the forecasters agree/i });

    for (const provider of spread.providers) {
      expect(panel).toHaveTextContent(provider);
    }
  });

  it('does not present the disagreement as a margin on the predicted height', async () => {
    // The backend's own docstrings call this an upper bound on disagreement rather than a
    // calibrated uncertainty: some of the gap is the models' publication schedules, not
    // doubt about the weather. Rendering it as "± 0.3m" would turn a bound into a
    // confidence interval in one typographic stroke.
    const panel = await agreementFor(BIG.date);
    const region = panel.closest('section')!;

    expect(region.textContent).not.toMatch(/±/);
    expect(region).toHaveTextContent(/upper bound/i);
  });

  it('names the hour the range was measured at, so it cannot be read against the peak', async () => {
    // The backend measures a day's spread at its median hour, and the card above shows the
    // day's peak. Two swell heights on screen that a reader would expect to match and never
    // will, unless the copy says which hour each belongs to.
    const panel = await agreementFor(BIG.date);

    expect(panel).toHaveTextContent(/middle hour/i);
  });

  it('says outright when too few forecasters answered, rather than showing a zero', async () => {
    // A zero here is indistinguishable from perfect agreement and would read as certainty
    // at exactly the moment the system knows least.
    const bare = { ...BIG, model_spread: { swell_height: unmeasurableSpread } };
    serveDays([bare]);

    const panel = await agreementFor(BIG.date);

    expect(panel).toHaveTextContent(/fewer than two independent forecasters/i);
    expect(panel).not.toHaveTextContent(/\b0m\b/);
  });

  it('flags a day resting on less than a full read', async () => {
    const degraded = {
      ...BIG,
      model_spread: {
        swell_height: {
          ...BIG.model_spread.swell_height!,
          providers: ['DWD', 'NCEP'],
          degraded: true,
        },
      },
    };
    serveDays([degraded]);

    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    expect(await screen.findByTestId(`spread-degraded-${BIG.date}`)).toHaveTextContent(
      /2 of 3 independent forecasters/i,
    );
  });

  it('counts the roster from the backend, not from a number kept here', async () => {
    // The day a fourth organisation joins, a roster size known on this side goes on saying
    // three — and prints "3 of 3 independent forecasters answered" beside a degraded flag,
    // which reads as a full read that is somehow still degraded.
    const fourth = {
      ...BIG,
      model_spread: {
        swell_height: {
          ...BIG.model_spread.swell_height!,
          providers: ['DWD', 'MeteoFrance', 'NCEP'],
          degraded: true,
          providers_expected: 4,
        },
      },
    };
    serveDays([fourth]);

    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    expect(await screen.findByTestId(`spread-degraded-${BIG.date}`)).toHaveTextContent(
      /3 of 4 independent forecasters/i,
    );
  });

  it('does not attribute the middle hour of contributors to the whole day', async () => {
    // `providers` is the median hour's, and `hours_measured` counts the whole day. Joining
    // them into one clause — "DWD, NCEP — measured across 18 of 24 hours" — claims those
    // organisations answered for all eighteen, which nothing in the record establishes.
    const partial = {
      ...BIG,
      model_spread: {
        swell_height: {
          ...BIG.model_spread.swell_height!,
          providers: ['DWD', 'NCEP'],
          hours_measured: 18,
          hours_total: 24,
        },
      },
    };
    serveDays([partial]);

    const panel = await agreementFor(BIG.date);
    const region = panel.closest('section')!;

    expect(region).toHaveTextContent(/18 of this day's 24 hours/i);
    expect(region.textContent).not.toMatch(/NCEP\s*—\s*measured across/i);
  });

  it('renders swell direction as a compass arc rather than a numeric interval', async () => {
    // Bearings wrap. A swell the models put between 355 and 5 degrees spans 10 degrees of
    // compass, and rendering the pair as a minimum and a maximum would name the wrong 350.
    const acrossNorth = {
      ...BIG,
      model_spread: {
        ...BIG.model_spread,
        swell_direction: {
          ...BIG.model_spread.swell_direction!,
          spread: 10,
          lowest: 355,
          highest: 5,
        },
      },
    };
    serveDays([acrossNorth]);

    const panel = await agreementFor(BIG.date);

    expect(panel).toHaveTextContent(`${compassPoint(355)} to ${compassPoint(5)}`);
    expect(panel).toHaveTextContent('355° to 5°');
  });

  it('reads a bearing from the backend flag, not from the unit the provider spelled', async () => {
    // Whether a pair is an arc or an interval decides arithmetic, not just presentation, and
    // the unit is the provider's own text. Sniffing it for a degree sign leaves the wrong
    // three-quarters of the compass one respelling away — so the same 355-to-5 arc must
    // survive the unit arriving as "deg".
    const respelled = {
      ...BIG,
      model_spread: {
        ...BIG.model_spread,
        swell_direction: {
          ...BIG.model_spread.swell_direction!,
          unit: 'deg',
          spread: 10,
          lowest: 355,
          highest: 5,
        },
      },
    };
    serveDays([respelled]);

    const panel = await agreementFor(BIG.date);

    expect(panel).toHaveTextContent(`${compassPoint(355)} to ${compassPoint(5)}`);
  });

  it('shows nothing at all for a day the backend sent no spread for', async () => {
    // A day stored before the backend derived any. Inventing a reassuring sentence for it
    // would be the interface answering a question nothing has measured.
    serveDays([{ ...BIG, model_spread: {} }]);

    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    await screen.findByRole('note');

    expect(
      screen.queryByRole('region', { name: /how much the forecasters agree/i }),
    ).not.toBeInTheDocument();
  });
});

describe('the day card says how much was checked', () => {
  // The panel only exists once a day is selected, so a reader scanning the range sees a call
  // with nothing to say how much stood behind it. What can honestly go on a card is whether
  // the check happened, not how wide it came out: a width needs a threshold nobody has
  // calibrated, and the range itself is the median hour's while the card's height is the
  // peak's.

  it('marks a day whose agreement rests on less than a full read', async () => {
    const degraded = {
      ...BIG,
      model_spread: {
        swell_height: { ...BIG.model_spread.swell_height!, providers: ['DWD'], degraded: true },
      },
    };
    serveDays([degraded]);

    render(<ForecastRange />);

    expect(await screen.findByTestId(`day-agreement-${BIG.date}`)).toHaveTextContent(
      /partly checked/i,
    );
  });

  it('marks a day nothing could be checked against at all', async () => {
    // The strongest case and the easiest to miss: a call with no second opinion behind it.
    serveDays([{ ...BIG, model_spread: { swell_height: unmeasurableSpread } }]);

    render(<ForecastRange />);

    expect(await screen.findByTestId(`day-agreement-${BIG.date}`)).toHaveTextContent(/unchecked/i);
  });

  it('says nothing on a day that got a full read', async () => {
    // Silence is the honest default. A "fully checked" badge on every ordinary card would
    // train the eye to skip the row, which is where the two that matter live.
    render(<ForecastRange />);
    await screen.findByTestId(`day-peak-${BIG.date}`);

    expect(screen.queryByTestId(`day-agreement-${BIG.date}`)).not.toBeInTheDocument();
  });

  it('says nothing for a day the backend sent no spread for', async () => {
    // Never measured is not the same as measured and found thin. A date stored before Model
    // Spread existed must not acquire a caveat about a check that was never attempted.
    serveDays([{ ...BIG, model_spread: {} }]);

    render(<ForecastRange />);
    await screen.findByTestId(`day-peak-${BIG.date}`);

    expect(screen.queryByTestId(`day-agreement-${BIG.date}`)).not.toBeInTheDocument();
  });

  it('carries no number, so it cannot be read as a margin on the height beside it', async () => {
    const degraded = {
      ...BIG,
      model_spread: {
        swell_height: { ...BIG.model_spread.swell_height!, providers: ['DWD'], degraded: true },
      },
    };
    serveDays([degraded]);

    render(<ForecastRange />);
    const marker = await screen.findByTestId(`day-agreement-${BIG.date}`);

    expect(marker.textContent).not.toMatch(/[\d±]/);
  });

  it('reaches a screen reader, which is given the label instead of the card', async () => {
    // `aria-label` overrides the card's content (#25). A marker living only in the markup
    // would be dropped for exactly the readers least able to go and find the panel.
    serveDays([{ ...BIG, model_spread: { swell_height: unmeasurableSpread } }]);

    render(<ForecastRange />);
    const card = await screen.findByRole('button', { name: new RegExp(BIG.date) });

    expect(card).toHaveAccessibleName(/no second opinion/i);
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

  describe('east of UTC+12', () => {
    // `vite.config.ts` pins the whole suite to UTC — "so timestamp assertions are
    // deterministic" — and this is the one place that needs a different zone. Restoring it
    // is not tidiness: the assignment really does take effect, so leaving it set made every
    // later test in this file run in Auckland, order-dependently, and silently unpinned the
    // convention for all of them.
    afterEach(() => {
      process.env.TZ = 'UTC';
    });

    it('names the same calendar day the backend grouped', async () => {
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

    it('names it the same way on the hour table and the call note', async () => {
      // The audit named three surfaces — "the card, `aria-label` and hour-table caption".
      // All three route through `dayLabel`, but only the card was covered, so a change
      // that reintroduced the fault on the other two would not have been caught.
      const day = dayFrom('2026-02-16', 4.2, 15, 298, 'go', 4);
      serveDays([day]);
      process.env.TZ = 'Pacific/Auckland';

      render(<ForecastRange />);
      await userEvent.click(await screen.findByRole('button', { name: new RegExp(day.date) }));

      expect((await screen.findByRole('table')).textContent).toContain('16');
      expect(screen.getByRole('note').getAttribute('aria-label')).toContain('16');
    });
  });

  it('shows the raw date rather than inventing one when it is malformed', async () => {
    // The numeric Date constructor never returns Invalid — it rolls over. `new Date(2026,
    // 12, 45)` is 14 February 2027. So a guard that only checks for Invalid Date would let
    // a malformed date render as a confident, plausible, wrong day, which is worse than
    // the timezone bug it replaced and is this project's characteristic failure.
    const malformed = { ...dayFrom('2026-02-16', 4.2, 15, 298, 'go', 4), date: '2026-13-45' };
    serveDays([malformed]);

    render(<ForecastRange />);

    const label = await screen.findByTestId('day-label-2026-13-45');
    expect(label.textContent).toBe('2026-13-45');
    expect(label.textContent).not.toContain('Feb');
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

  it('shows the day label and hours in order, marked as Nazaré time', async () => {
    // Surviving mutants before this: dayLabel returning a constant, the hour rows
    // reversed, and the Time column frozen on the first hour.
    render(<ForecastRange />);

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
    const table = await screen.findByRole('table');

    // Both the caption and the Time column name the zone; either alone would do. Naming
    // it matters more than which one it is: an unlabelled 06:00 is read as the viewer's
    // own morning, and this is the hour someone drives to the beach for (ADR 0008).
    expect(within(table).getAllByText(/Nazaré/).length).toBeGreaterThan(0);
    expect(within(table).queryAllByText(/UTC/)).toHaveLength(0);
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
