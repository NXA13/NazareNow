/**
 * The forecast range, driven through what a user sees and does.
 *
 * Same seam as App.test.tsx: the API is mocked at the network boundary and only visible
 * behaviour is asserted. Assertions target fixture values so none can pass by matching
 * static copy — a mistake this suite has shipped twice.
 *
 * **`toHaveTextContent` matches substrings.** `toHaveTextContent('82%')` is satisfied by a
 * page rendering `0.82%`, and `toHaveTextContent('6.1')` by one rendering `16.1`. Where the
 * point of an assertion is that a number is *this* number rather than one containing it,
 * match on `textContent` with a bounded pattern instead. The percentage test below existed
 * to forbid `0.82` and passed on `0.82` for exactly this reason.
 */

import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it } from 'vitest';

import { type CallStatus } from './api';
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

  it('says which Gold Days chose the thresholds and which were held back to check them', async () => {
    // Asserting that both numbers appear leaves them free to swap places: a 6/3 split
    // rendered as "3 to choose them and 6 held back" keeps both figures on the page and
    // passes. It also reverses what the caveat exists to disclose, claiming the fit rests
    // on half the days it does and that twice as many were held back to check it — the
    // more reassuring of the two readings, which is the direction this project keeps
    // having to undo. Each number is pinned to its own clause.
    server.use(
      http.get('*/api/conditions/forecast', () =>
        HttpResponse.json({ ...forecast, calibrated: true, calibration }),
      ),
    );

    render(<ForecastRange />);

    const note = await screen.findByRole('status');
    expect(note.textContent).toContain(`${calibration.gold_days_fitted} to choose them`);
    expect(note.textContent).toContain(`${calibration.gold_days_validated} held back`);
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

  it('counts them in the sentence from the backend, not from a number kept here', async () => {
    // The names above were asserted; the count beside them was not, and every fixture that
    // reached this sentence carried the full roster of three. Freezing the number at 3
    // passed — and on a two-forecaster day it would print "3 independent forecasters"
    // directly above a banner reading "2 of 3 answered", contradicting itself on screen.
    const two = {
      ...BIG,
      model_spread: {
        swell_height: { ...BIG.model_spread.swell_height!, providers: ['DWD', 'NCEP'] },
      },
    };
    serveDays([two]);

    const panel = await agreementFor(BIG.date);

    expect(panel).toHaveTextContent(/\b2 independent forecasters\b/);
  });

  it('says how far apart they are on the period, not only on the height', async () => {
    // Nothing asserted the period clause at all, so deleting it outright passed. Period is
    // the condition that actually binds a giant day — CONTEXT.md's Swell Period entry and
    // #66 both turn on it — so a disagreement about it is worth at least as much to a
    // reader as one about the height. Asserted as value-and-word in a single phrase: the
    // number alone would be satisfied by the height sentence if the two ever coincided.
    const period = BIG.model_spread.swell_period!;

    const panel = await agreementFor(BIG.date);

    expect(panel.textContent).toContain(`${period.spread}${period.unit} on the period`);
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

  it('marks a Go Call the wave models refused, so it does not read as a plain Watch', async () => {
    // The card would otherwise say "Watch" and nothing else, and this is a swell the system
    // believes in that the forecasters have not settled on — a different day from one that
    // was never big enough, and the difference is why somebody keeps checking back.
    serveDays([
      {
        ...BIG,
        call: {
          ...BIG_CALL,
          status: 'watch' as const,
          model_agreement: 'divided' as const,
          go_call_withheld: true,
        },
      },
    ]);

    render(<ForecastRange />);

    expect(await screen.findByTestId(`day-agreement-${BIG.date}`)).toHaveTextContent(
      /models divided/i,
    );
  });

  it('puts a refused Go Call ahead of how much was checked, when a day is both', async () => {
    // `agreementFlag` states this precedence outright — a refusal outranks both markers,
    // because it is the only one of them that changed what the card says. Nothing tested
    // it: every fixture with a withheld Go Call carried a full spread, and every thin
    // spread came on a day nothing had refused. So the two branches never competed, and
    // reordering them to let "partly checked" win passed the whole suite.
    serveDays([
      {
        ...BIG,
        model_spread: {
          swell_height: { ...BIG.model_spread.swell_height!, providers: ['DWD'], degraded: true },
        },
        call: {
          ...BIG_CALL,
          status: 'watch' as const,
          model_agreement: 'divided' as const,
          go_call_withheld: true,
        },
      },
    ]);

    render(<ForecastRange />);

    expect(await screen.findByTestId(`day-agreement-${BIG.date}`)).toHaveTextContent(
      /models divided/i,
    );
  });

  it('does not call the models divided when they were simply unreachable', async () => {
    // Both withhold a Go Call and they are not the same fact. "The forecasters disagree"
    // said about an endpoint that never answered is an invented finding.
    serveDays([
      {
        ...BIG,
        call: {
          ...BIG_CALL,
          status: 'watch' as const,
          model_agreement: 'unmeasured' as const,
          go_call_withheld: true,
        },
      },
    ]);

    render(<ForecastRange />);

    const marker = await screen.findByTestId(`day-agreement-${BIG.date}`);
    expect(marker).toHaveTextContent(/unchecked/i);
    expect(marker).not.toHaveTextContent(/divided/i);
  });

  it('says nothing on a Watch the models never had a Go Call to withhold', async () => {
    // A day under the Go Call bar reports `divided` as a matter of arithmetic — every
    // forecaster is under a bar the day itself misses. Marking that would put a caveat on
    // most of the quiet days in the range and teach the eye to skip the row.
    serveDays([
      {
        ...BIG,
        call: {
          ...BIG_CALL,
          status: 'watch' as const,
          model_agreement: 'divided' as const,
          go_call_withheld: false,
        },
      },
    ]);

    render(<ForecastRange />);
    await screen.findByTestId(`day-peak-${BIG.date}`);

    expect(screen.queryByTestId(`day-agreement-${BIG.date}`)).not.toBeInTheDocument();
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

describe('how sure the forecast is', () => {
  /** Open a day and return its detail panel. */
  async function detailFor(date: string, days?: unknown[]) {
    if (days) {
      server.use(
        http.get('*/api/conditions/forecast', () => HttpResponse.json({ ...forecast, days })),
      );
    }
    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(date) }));
    return screen.findByTestId(`confidence-${date}`);
  }

  it('states the plausible range in metres rather than a bare percentage', async () => {
    // #15's whole point. "78% confident" is not something a person can act on; the two
    // heights the forecast plausibly lands between are. Asserted against the fixture so it
    // cannot pass on static copy.
    const range = BIG_CALL.plausible_range!;

    const panel = await detailFor(BIG.date);

    expect(panel).toHaveTextContent(`${range.low}${range.unit} to ${range.high}${range.unit}`);
  });

  it('states the chance of clearing the height bar as a percentage a reader can scan', async () => {
    // The backend sends a share between 0 and 1 and leaves the rounding here, so the figure
    // is stated in one place. 0.82 must reach the page as 82%, not as 0.82.
    //
    // `toHaveTextContent('82%')` could not say that. It matches substrings, and "0.82%"
    // contains "82%" — so deleting the `* 100` rendered the raw share and passed the one
    // assertion written to forbid exactly that. The lookbehind is what carries the claim:
    // nothing that reads as a decimal may sit in front of the number. Derived from the
    // fixture rather than written as a literal, so the two cannot drift apart.
    const percentage = Math.round(BIG_CALL.height_bar_probability! * 100);

    const panel = await detailFor(BIG.date);

    expect(panel.textContent).toMatch(new RegExp(`(?<![\\d.])${percentage}%`));
    expect(panel).not.toHaveTextContent(`${BIG_CALL.height_bar_probability}%`);
  });

  it('does not offer that percentage as the chance of a giant day', async () => {
    // #66. The number prices one of the four conditions a giant day needs, and the copy read
    // "likely to reach the size this system calls a giant day" — careful about size, but sat
    // close enough to the claim that a reader could take the percentage for the whole thing.
    const panel = await detailFor(BIG.date);

    expect(panel).toHaveTextContent(/clear the minimum significant wave height/i);
    expect(panel).not.toHaveTextContent(/likely to (be|reach) a giant day/i);
  });

  it('names the quantity rather than calling it the size of the wave', async () => {
    // CONTEXT.md puts "wave size" on Face Height's Avoid list, and this bar is on the
    // Combined Sea 15km offshore. "The minimum size for a giant day", sitting beside the
    // words "giant day", invites the Face Height reading the glossary exists to prevent.
    const panel = await detailFor(BIG.date);

    expect(panel).toHaveTextContent(/significant wave height/i);
    expect(panel).not.toHaveTextContent(/minimum size/i);
  });

  it('says which conditions the percentage leaves out', async () => {
    // Naming them, not merely hedging. "Size only" on its own asks the reader to already know
    // what the other conditions are; the three that are missing are the useful half.
    const panel = await detailFor(BIG.date);

    expect(panel).toHaveTextContent(/swell period/i);
    expect(panel).toHaveTextContent(/swell direction/i);
    expect(panel).toHaveTextContent(/wind/i);
  });

  it('says nothing about scope when there is no percentage to scope', async () => {
    // A call from before the pipeline built distributions renders no figure, and a bare
    // "size only" under nothing at all would be a caveat on a number that is not there.
    const withoutProbability = {
      ...BIG,
      call: { ...BIG_CALL, height_bar_probability: null },
    };

    const panel = await detailFor(BIG.date, [
      forecast.days[0],
      withoutProbability,
      forecast.days[2],
    ]);

    expect(panel).not.toHaveTextContent(/height only/i);
  });

  it('says the range is not measured beyond the archive, and says why', async () => {
    // The sixth criterion. The width out there keeps growing at the rate the archive
    // measured, but nothing was measured about that lead time — and an extrapolation
    // rendered identically to a measurement is the failure this flag exists to prevent.
    const beyond = {
      ...BIG,
      call: { ...BIG_CALL, uncertainty_measured: false, lead_time_days: 10 },
    };

    const panel = await detailFor(BIG.date, [forecast.days[0], beyond, forecast.days[2]]);

    expect(panel).toHaveTextContent(/nothing has been measured/i);
    // And says what the limit actually is, rather than only that there is one.
    expect(panel).toHaveTextContent(/seven days/i);
    expect(within(panel).getByRole('status')).toBeInTheDocument();
  });

  it('does not cry unmeasured for a date inside the archive', async () => {
    const panel = await detailFor(BIG.date);

    expect(within(panel).queryByRole('status')).not.toBeInTheDocument();
  });

  it('separates a Go Call the width refused from one the forecasters refused', async () => {
    // Both end in a Watch and they are different facts about the world. A reader told only
    // "Watch" cannot tell a swell the forecasters have not settled on from one the forecast
    // is simply too uncertain about to book on.
    const uncertain = {
      ...BIG,
      call: {
        ...BIG_CALL,
        status: 'watch' as const,
        go_call_withheld: false,
        go_call_withheld_for_uncertainty: true,
      },
    };

    const panel = await detailFor(BIG.date, [forecast.days[0], uncertain, forecast.days[2]]);

    expect(panel).toHaveTextContent(/too uncertain/i);
    expect(panel).not.toHaveTextContent(/forecasters do not agree/i);
  });
});

describe('swells spanning more than a day', () => {
  /**
   * Story 25 of #1, and the one closest to what the product is for: nobody flies to Portugal
   * for an afternoon, so the unit a person books is a trip and the range rendered a three-day
   * swell as three verdicts that happened to sit next to each other.
   *
   * Dates are asserted through the `dateTime` attribute of each `time` element rather than
   * through its rendered text. The suite pins the zone and not the locale, so "13 Feb" and
   * "Feb 13" are both correct renderings — and asserting the text would either be
   * locale-fragile or would compare `dayLabel` against its own output, which is how the
   * compass rose passed for any ordering of the sixteen points (#78).
   */
  async function windowsFor(days: unknown[]) {
    server.use(
      http.get('*/api/conditions/forecast', () => HttpResponse.json({ ...forecast, days })),
    );
    render(<ForecastRange />);
    return screen.findByTestId('swell-windows');
  }

  const dateOf = (scope: HTMLElement, testId: string) =>
    within(scope).getByTestId(testId).getAttribute('datetime');

  it('gathers a run of called days into one window and names its span', async () => {
    const days = [
      dayFrom('2026-02-12', 4.0, 14, 300, 'watch', 3),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 2),
      dayFrom('2026-02-14', 5.1, 15, 300, 'watch', 1),
    ];

    const section = await windowsFor(days);
    const windows = within(section).getAllByRole('listitem');

    expect(windows).toHaveLength(1);
    expect(dateOf(windows[0]!, 'window-start')).toBe('2026-02-12');
    expect(dateOf(windows[0]!, 'window-end')).toBe('2026-02-14');
    expect(windows[0]!.textContent).toContain('3 days');
  });

  it('names the largest day of a window, not its first', async () => {
    // The peak is what a trip is planned around. Picked by order rather than by size, this
    // sentence still reads perfectly and points at the wrong day — and on a building swell,
    // which is the common shape, it would always point at the smallest.
    const days = [
      dayFrom('2026-02-12', 4.0, 14, 300, 'watch', 3),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 2),
      dayFrom('2026-02-14', 5.1, 15, 300, 'watch', 1),
    ];

    const section = await windowsFor(days);

    expect(dateOf(within(section).getAllByRole('listitem')[0]!, 'window-peak')).toBe('2026-02-13');
  });

  it('ends a window at a quiet day rather than reaching across it', async () => {
    // The judgement call this ticket names. Two swells either side of a lull may be one event
    // or two, and nothing here can tell them apart — so the rule takes the shorter reading,
    // because the failure worth avoiding is somebody booking five nights against a
    // three-night event.
    const days = [
      dayFrom('2026-02-12', 5.0, 15, 300, 'go', 3),
      dayFrom('2026-02-13', 6.1, 16, 300, 'go', 2),
      dayFrom('2026-02-14', 1.1, 7, 300, 'none', 1),
      dayFrom('2026-02-15', 5.4, 15, 300, 'go', 0),
      dayFrom('2026-02-16', 5.6, 15, 300, 'watch', 0),
    ];

    const section = await windowsFor(days);
    const windows = within(section).getAllByRole('listitem');

    expect(windows).toHaveLength(2);
    expect(dateOf(windows[0]!, 'window-end')).toBe('2026-02-13');
    expect(dateOf(windows[1]!, 'window-start')).toBe('2026-02-15');
  });

  it('states the rule that a quiet day ends a window', async () => {
    // A reader cannot judge a window without knowing what it excludes, and this rule is a
    // choice rather than a fact about the ocean.
    const section = await windowsFor([
      dayFrom('2026-02-12', 5.0, 15, 300, 'go', 1),
      dayFrom('2026-02-13', 6.1, 16, 300, 'go', 0),
    ]);

    expect(section).toHaveTextContent(/quiet day ends one/i);
    expect(section).toHaveTextContent(/counted as two windows and not one/i);
  });

  it('does not announce a single called day as a window', async () => {
    // It is already a card in the range. "A swell spanning 1 day" is a sentence about nothing.
    const days = [
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 3),
      dayFrom('2026-02-13', 6.1, 16, 300, 'go', 2),
      dayFrom('2026-02-14', 1.1, 7, 300, 'none', 1),
    ];

    const section = await windowsFor(days);

    expect(within(section).queryAllByRole('listitem')).toHaveLength(0);
    // Visible, not merely present. `getByTestId` finds a `hidden` element and
    // `toHaveTextContent` reads it, so the assertion written to prove a reader is told
    // something passes on markup no reader can see.
    expect(within(section).getByTestId('no-windows')).toBeVisible();
  });

  it('says plainly when nothing spans more than a day', async () => {
    // Story 12 one level up: an absent section reads as a page that failed, and most of the
    // year this is the honest answer rather than an omission.
    const section = await windowsFor([
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 2),
      dayFrom('2026-02-13', 1.1, 7, 300, 'none', 1),
    ]);

    const statement = within(section).getByTestId('no-windows');

    expect(statement).toBeVisible();
    expect(statement).toHaveTextContent(/no multi-day window to plan a trip around/i);
  });

  it('leaves every day inside a window with the verdict it was given', async () => {
    // A window must invent no status. Story 12 requires a quiet day shown as quiet, and a
    // window that promoted its members would break it exactly where a reader is about to act.
    const days = [
      dayFrom('2026-02-12', 4.0, 14, 300, 'watch', 3),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 2),
      dayFrom('2026-02-14', 5.1, 15, 300, 'watch', 1),
    ];

    await windowsFor(days);

    for (const [date, label] of [
      ['2026-02-12', 'Watch'],
      ['2026-02-13', 'Go'],
      ['2026-02-14', 'Watch'],
    ] as const) {
      const card = await screen.findByRole('button', { name: new RegExp(date) });
      expect(within(card).getByText(label)).toBeInTheDocument();
    }
  });

  it('counts the Go Call days inside a window, not the days in it', async () => {
    // Two counts of days in one sentence, out of the same window. Rendering the length where
    // the Go Call count belongs claims every day of the window is bookable, which is the
    // flattering direction and the one that costs a flight.
    const days = [
      dayFrom('2026-02-12', 4.0, 14, 300, 'watch', 3),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 2),
      dayFrom('2026-02-14', 5.1, 15, 300, 'watch', 1),
    ];

    const section = await windowsFor(days);

    expect(section.textContent).toContain('1 of those days carries a Go Call');
  });

  it('says so when a window carries no Go Call at all', async () => {
    const days = [
      dayFrom('2026-02-12', 4.0, 14, 300, 'watch', 3),
      dayFrom('2026-02-13', 4.4, 14, 300, 'watch', 2),
    ];

    const section = await windowsFor(days);

    expect(section.textContent).toContain('None of those days carries a Go Call');
  });

  it('does not join two called days that are not consecutive dates', async () => {
    // Adjacency is a calendar question, not a position-in-the-array one. A range with a day
    // missing would otherwise render two dates a week apart as one continuous swell.
    const days = [
      dayFrom('2026-02-12', 5.0, 15, 300, 'go', 3),
      dayFrom('2026-02-19', 6.1, 16, 300, 'go', 2),
    ];

    const section = await windowsFor(days);

    expect(within(section).queryAllByRole('listitem')).toHaveLength(0);
  });

  it('joins days across a month boundary', async () => {
    // The arithmetic that string comparison gets wrong. 28 February and 1 March are adjacent
    // and read as six months apart to anything comparing the day number alone.
    const days = [
      dayFrom('2026-02-28', 5.0, 15, 300, 'go', 1),
      dayFrom('2026-03-01', 6.1, 16, 300, 'go', 0),
    ];

    const section = await windowsFor(days);
    const windows = within(section).getAllByRole('listitem');

    expect(windows).toHaveLength(1);
    expect(dateOf(windows[0]!, 'window-end')).toBe('2026-03-01');
  });
});

describe('the earliest date worth acting on', () => {
  /**
   * Story 23 of #1, finished. Every date already renders with its status, so the answer a
   * Traveller actually wants — *is there anything worth booking, and when* — was reachable
   * only by scanning a fourteen-day list and assembling it. Nothing stated it.
   *
   * Dates are asserted through `dateTime` rather than rendered text, for the reason the
   * windows suite above gives: the suite pins the zone and not the locale.
   */
  async function statementFor(days: unknown[]) {
    server.use(
      http.get('*/api/conditions/forecast', () => HttpResponse.json({ ...forecast, days })),
    );
    render(<ForecastRange />);
    return screen.findByTestId('earliest-call');
  }

  const dateOf = (scope: HTMLElement, testId: string) =>
    within(scope).getByTestId(testId).getAttribute('datetime');

  it('names the earliest Go Call and says to book it', async () => {
    const statement = await statementFor([
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 3),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 2),
    ]);

    expect(statement).toBeVisible();
    expect(dateOf(statement, 'earliest-date')).toBe('2026-02-13');
    expect(statement).toHaveTextContent(/book for/i);
  });

  it('picks the earliest Go Call rather than the largest', async () => {
    // The largest day is the one a reader's eye lands on in the range below, and it is not
    // the one this sentence is about: story 23 asks for the *earliest* date, because that is
    // the one whose flights are still bookable. Picking by size reads perfectly and answers
    // a different question.
    const statement = await statementFor([
      dayFrom('2026-02-12', 5.0, 15, 300, 'go', 4),
      dayFrom('2026-02-13', 9.4, 18, 300, 'go', 3),
    ]);

    expect(dateOf(statement, 'earliest-date')).toBe('2026-02-12');
  });

  it('prefers a Go Call to a Watch that falls earlier', async () => {
    // The fallback is a fallback. A Watch tells a reader to start paying attention and a Go
    // Call tells them to spend money, so a sentence that led with an earlier Watch while a
    // Go Call sat behind it in the range would bury the only thing worth acting on.
    const statement = await statementFor([
      dayFrom('2026-02-12', 4.0, 14, 300, 'watch', 4),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 3),
    ]);

    expect(dateOf(statement, 'earliest-date')).toBe('2026-02-13');
    expect(statement).toHaveTextContent(/book for/i);
    expect(statement.textContent).not.toMatch(/nothing to book/i);
  });

  it('falls back to the earliest Watch, and does not call it bookable', async () => {
    const statement = await statementFor([
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 4),
      dayFrom('2026-02-13', 4.0, 14, 300, 'watch', 3),
      dayFrom('2026-02-14', 4.4, 14, 300, 'watch', 2),
    ]);

    expect(dateOf(statement, 'earliest-date')).toBe('2026-02-13');
    expect(statement).toHaveTextContent(/nothing to book/i);
    expect(statement).toHaveTextContent(/do not book on it/i);
  });

  it('states the Lead Time the call was issued at, not the date alone', async () => {
    // Story 20. "On the 13th" and "three days ahead" answer different questions and the
    // booking one needs both — a date with no notice attached says nothing about whether
    // there is still time to act on it.
    const days = [
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 4),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 3),
    ];

    const statement = await statementFor(days);

    expect(statement.textContent).toContain(`issued ${days[1]!.call!.lead_time_days} days ahead`);
  });

  it('states the Lead Time on the Watch fallback too', async () => {
    // Same obligation, the other branch. A reader deciding whether to keep watching needs to
    // know how far out the Watch was raised as much as a reader deciding whether to book.
    const days = [dayFrom('2026-02-14', 4.0, 14, 300, 'watch', 9)];

    const statement = await statementFor(days);

    expect(statement.textContent).toContain(`issued ${days[0]!.call!.lead_time_days} days ahead`);
  });

  it('says plainly when nothing in range carries either, as an answer and not a fault', async () => {
    // The quiet case is the common case. Story 12's reason, one level up again: a statement
    // that renders nothing is indistinguishable from a page that failed to load, and most of
    // the year this sentence is the truthful answer to "is there a trip here".
    const statement = await statementFor([
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 2),
      dayFrom('2026-02-13', 1.1, 7, 300, 'none', 1),
    ]);

    // Visible, not merely present: `getByTestId` finds a hidden element and
    // `toHaveTextContent` reads it happily.
    expect(statement).toBeVisible();
    expect(statement).toHaveTextContent(/no day .* carries a Go Call or a Watch/i);
    // An answer, not a warning. Rendered as an alert it would read as the system failing to
    // forecast rather than the ocean being ordinary.
    expect(statement).not.toHaveAttribute('role', 'alert');
  });

  it('does not offer a Confirmed day as something to book', async () => {
    // A deliberate departure from the ladder a reader might expect. CONTEXT.md makes Confirmed
    // a short-range statement to somebody already travelling, carrying no booking
    // recommendation — so it is not a thing to act on, and #84 settled that the four statuses
    // have no ordering to promote it through. The quiet sentence must stay true beside one:
    // it says no Go Call and no Watch, which a Confirmed day does not contradict.
    const statement = await statementFor([dayFrom('2026-02-12', 7.2, 17, 300, 'confirmed', 0)]);

    expect(statement).toHaveTextContent(/no day .* carries a Go Call or a Watch/i);
    expect(statement.textContent).not.toMatch(/book for/i);
  });

  it('names the window a Go Call falls inside rather than the date alone', async () => {
    // #85 shipped the unit a person actually books. The earliest thing worth acting on is
    // that window and not a bare date, so the two compose: the Go Call is the commitment and
    // the window is the shape of the trip around it.
    const statement = await statementFor([
      dayFrom('2026-02-12', 4.0, 14, 300, 'watch', 4),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 3),
      dayFrom('2026-02-14', 5.1, 15, 300, 'watch', 2),
    ]);

    expect(dateOf(statement, 'earliest-window-start')).toBe('2026-02-12');
    expect(dateOf(statement, 'earliest-window-end')).toBe('2026-02-14');
    expect(statement.textContent).toContain('3-day swell');
  });

  it('says nothing about a window when the day stands alone', async () => {
    // A single called day is not a window — #85's rule, and inventing a one-day one here
    // would put a trip-shaped sentence around an afternoon.
    const statement = await statementFor([
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 3),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 2),
      dayFrom('2026-02-14', 1.1, 7, 300, 'none', 1),
    ]);

    expect(within(statement).queryByTestId('earliest-window-start')).not.toBeInTheDocument();
    expect(statement.textContent).not.toMatch(/swell running|-day swell/i);
  });

  it('sits above the range it summarises', async () => {
    // Story 28: the answer should not need navigating to. Below fourteen day cards it is not
    // an answer, it is a footnote to the scan it exists to replace.
    const statement = await statementFor([
      dayFrom('2026-02-12', 1.2, 7, 300, 'none', 3),
      dayFrom('2026-02-13', 7.2, 17, 300, 'go', 2),
    ]);

    const card = await screen.findByRole('button', { name: /2026-02-13/ });
    expect(statement.compareDocumentPosition(card)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});

describe('how the prediction has moved', () => {
  async function detailFor(date: string, days: unknown[]) {
    server.use(
      http.get('*/api/conditions/forecast', () => HttpResponse.json({ ...forecast, days })),
    );
    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(date) }));
    return screen.findByTestId(`shift-${date}`);
  }

  const earlier = (value: number, lead: number, issued: string, status: CallStatus = 'watch') => ({
    issued_at: issued,
    lead_time_days: lead,
    status,
    predicted_significant_wave_height: { value, unit: 'm' },
    plausible_range: { low: value - 1.2, high: value + 1.9, unit: 'm' },
  });

  it('says which way the prediction has moved since the run before', async () => {
    // #15's eighth criterion. A swell building between runs is the signal a traveller is
    // waiting for, and a number that simply replaces the previous one shows nothing.
    const building = {
      ...BIG,
      call: {
        ...BIG_CALL,
        predicted_significant_wave_height: { value: 6.4, unit: 'm' },
        previous_runs: [
          earlier(4.1, 9, '2026-02-08T06:00:00Z'),
          earlier(5.2, 8, '2026-02-09T06:00:00Z'),
        ],
      },
    };

    const panel = await detailFor(BIG.date, [forecast.days[0], building, forecast.days[2]]);

    expect(panel).toHaveTextContent(/1.2m larger|up 1.2m/i);
    expect(panel).toHaveTextContent('5.2m');
  });

  it('says when the prediction has come down as readily as when it has risen', async () => {
    // A fading swell is as much a reason to act — by not booking — as a building one, and a
    // display that only knew how to say "building" would be telling half the truth.
    const fading = {
      ...BIG,
      call: {
        ...BIG_CALL,
        predicted_significant_wave_height: { value: 3.0, unit: 'm' },
        previous_runs: [earlier(5.0, 8, '2026-02-09T06:00:00Z')],
      },
    };

    const panel = await detailFor(BIG.date, [forecast.days[0], fading, forecast.days[2]]);

    expect(panel).toHaveTextContent(/2m smaller|down 2m/i);
  });

  it('says a run that barely moved did not move, rather than drawing a change of zero', async () => {
    // The whole `Unchanged since the run before` branch was dead to this suite: both
    // fixtures moved by metres, so the threshold that selects it could be deleted and
    // nothing noticed. A 0.02m move is below the rounding the page displays at, and
    // reporting it as "0m larger" is a sentence about nothing dressed as a finding.
    const steady = {
      ...BIG,
      call: {
        ...BIG_CALL,
        predicted_significant_wave_height: { value: 6.4, unit: 'm' },
        previous_runs: [earlier(6.42, 8, '2026-02-09T06:00:00Z')],
      },
    };

    const panel = await detailFor(BIG.date, [forecast.days[0], steady, forecast.days[2]]);

    expect(panel).toHaveTextContent(/unchanged since the run before/i);
    expect(panel.textContent).not.toMatch(/larger|smaller/i);
  });

  it('names the lead time the earlier run spoke at', async () => {
    // A range narrowing as the date approaches is the forecast doing its job; the same
    // narrowing at a fixed lead time is something else entirely, and a reader cannot tell
    // which they are looking at without this. The clause was unasserted, so dropping it
    // passed — leaving a comparison against a run whose distance from the day is unstated.
    const previous = earlier(5.2, 8, '2026-02-09T06:00:00Z');
    const building = {
      ...BIG,
      call: {
        ...BIG_CALL,
        predicted_significant_wave_height: { value: 6.4, unit: 'm' },
        previous_runs: [previous],
      },
    };

    const panel = await detailFor(BIG.date, [forecast.days[0], building, forecast.days[2]]);

    expect(panel).toHaveTextContent(`${previous.lead_time_days} days out`);
  });

  it('says nothing about movement on the first run that mentions a date', async () => {
    // Empty is the honest answer, and a date compared against itself would draw a shift of
    // exactly zero and read as settled.
    render(<ForecastRange />);
    await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

    expect(screen.queryByTestId(`shift-${BIG.date}`)).not.toBeInTheDocument();
  });

  describe('when the verdict itself has moved', () => {
    /**
     * Story 21 of #1. `EarlierCall` has always carried `status` and nothing read it, so a day
     * that carried a Watch last run and nothing this run rendered exactly like a day that had
     * never been called — for a reader who has spent a week watching flights.
     *
     * No fixture had ever set an earlier status differing from the current one, which is why
     * the whole branch could not have failed.
     */
    async function tierChangeFor(now: CallStatus, before: CallStatus) {
      const day = {
        ...BIG,
        call: {
          ...BIG_CALL,
          status: now,
          previous_runs: [earlier(5.0, 8, '2026-02-09T06:00:00Z', before)],
        },
      };
      server.use(
        http.get('*/api/conditions/forecast', () =>
          HttpResponse.json({ ...forecast, days: [forecast.days[0], day, forecast.days[2]] }),
        ),
      );
      render(<ForecastRange />);
      await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
      return screen.findByTestId(`tier-change-${BIG.date}`);
    }

    it('says a Watch has been withdrawn, and names the tier that was withdrawn', async () => {
      // Naming the tier is half the sentence. Rendering the *current* status where the
      // earlier one belongs makes a withdrawn Watch read "The No call on this day has been
      // withdrawn" — a sentence about nothing, in a paragraph that still looks right.
      const statement = await tierChangeFor('none', 'watch');

      expect(statement).toHaveTextContent(/withdrawn/i);
      expect(statement.textContent).toContain('Watch');
      expect(statement.textContent).not.toContain('No call on this day has been withdrawn');
    });

    it('tells a reader to stop watching flights for a withdrawn day', async () => {
      // The story is not "show a state change". It is that somebody stops spending attention
      // on a swell that has evaporated, which is the sentence that does the work.
      const statement = await tierChangeFor('none', 'watch');

      expect(statement).toHaveTextContent(/stop watching flights/i);
    });

    it('says a day has become a Go Call, which is the transition worth catching', async () => {
      const statement = await tierChangeFor('go', 'watch');

      expect(statement).toHaveTextContent(/now a go call/i);
      expect(statement.textContent).toContain('Watch');
      expect(statement).not.toHaveTextContent(/withdrawn/i);
    });

    it('says a day never called before has been newly raised', async () => {
      const statement = await tierChangeFor('watch', 'none');

      expect(statement).toHaveTextContent(/newly raised/i);
      expect(statement).not.toHaveTextContent(/withdrawn/i);
    });

    it('states a change between two calls without ranking them', async () => {
      // Confirmed is not a stronger Go. ADR 0003 makes it a short-range statement to somebody
      // already travelling, carrying no booking recommendation — so a day moving from Go to
      // Confirmed as it approaches has not weakened, and printing a judgement word on it would
      // invent a scale the domain does not have.
      const statement = await tierChangeFor('confirmed', 'go');

      expect(statement.textContent).toContain('Go');
      expect(statement.textContent).toContain('Confirmed');
      expect(statement).not.toHaveTextContent(/withdrawn|weaker|weakened|downgrad/i);
    });

    it('says nothing when the tier has not moved, however far the height has', async () => {
      // The height sentence and the tier sentence answer different questions, and a tier
      // paragraph on every day would train a reader to skip the one day it matters on.
      const unchanged = {
        ...BIG,
        call: {
          ...BIG_CALL,
          status: 'go' as const,
          predicted_significant_wave_height: { value: 6.4, unit: 'm' },
          previous_runs: [earlier(3.1, 8, '2026-02-09T06:00:00Z', 'go')],
        },
      };

      const panel = await detailFor(BIG.date, [forecast.days[0], unchanged, forecast.days[2]]);

      expect(panel).toHaveTextContent(/larger/);
      expect(screen.queryByTestId(`tier-change-${BIG.date}`)).not.toBeInTheDocument();
    });

    it('says nothing about the tier on the first run that mentions a date', async () => {
      render(<ForecastRange />);
      await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));

      expect(screen.queryByTestId(`tier-change-${BIG.date}`)).not.toBeInTheDocument();
    });

    it('does not call a withdrawal a withholding', async () => {
      // The page already says "withheld" of the Model Spread gate refusing a Go Call within a
      // single run. This is a different event — the system changing its mind between runs —
      // and a reader meeting both words on one page must not read them as one. #76.
      const statement = await tierChangeFor('none', 'watch');

      expect(statement).not.toHaveTextContent(/withheld|withhold/i);
    });
  });
});
