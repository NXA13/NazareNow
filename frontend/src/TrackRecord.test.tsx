/**
 * The track record page, driven through what a reader sees.
 *
 * Same seam as the rest of the suite: the API is mocked at the network boundary and only
 * visible behaviour is asserted, against fixture values rather than against copy — this
 * suite has twice shipped a test that passed by matching static text.
 *
 * The asymmetry that shapes every test here: on this page a figure that is too kind is a
 * defect and a figure that is too harsh is merely disappointing. So the assertions are
 * about what the page refuses to imply as much as about what it renders — the baseline
 * beside every accuracy figure, the tiers apart, the missed days present, and the wasted
 * trips stated rather than left as an inversion for the reader to perform.
 */

import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { TrackRecordPage } from './TrackRecord';
import { trackRecord } from './test/handlers';
import { server } from './test/server';

/** Serve a track record with some fields replaced, leaving the rest alone. */
function serve(changes: Partial<typeof trackRecord>) {
  server.use(
    http.get('*/api/track-record', () => HttpResponse.json({ ...trackRecord, ...changes })),
  );
}

describe('both models, always together', () => {
  /**
   * The criterion #16 names explicitly, and the reason ADR 0006 exists.
   *
   * Asserted per row rather than per page: a table that renders the learned model's
   * column and drops the baseline's would still leave the word "rule of thumb" in the
   * header, so a page-level text assertion passes on exactly the defect this guards.
   */
  it('shows the rule of thumb beside the learned model in every accuracy row', async () => {
    render(<TrackRecordPage />);

    for (const testId of ['scored-accuracy', 'served-accuracy']) {
      const table = await screen.findByTestId(testId);
      const bands = testId === 'scored-accuracy' ? trackRecord.scored : trackRecord.served;

      for (const band of bands) {
        const row = within(table).getByRole('row', { name: new RegExp(band.name) });
        expect(within(row).getByText(`${band.baseline_mae_m.toFixed(2)}m`)).toBeInTheDocument();
        expect(within(row).getByText(`${band.learned_mae_m.toFixed(2)}m`)).toBeInTheDocument();
      }
    }
  });

  it('refuses the whole record rather than show the learned model unopposed', async () => {
    // The type requires both errors, but the body arriving from the network is untyped, so
    // the promise needs a runtime edge. Refusal rather than a dropped row: a shorter table
    // carries no sign that it was ever longer, and the row that goes missing is the one
    // whose absence flatters. This asserted a dropped row until the page crashed in the
    // number formatter instead, which renders as a blank section — the worst of the three.
    serve({
      scored: [
        {
          name: 'all hours',
          hours: 28426,
          learned_mae_m: 0.207,
        } as unknown as (typeof trackRecord.scored)[number],
      ],
    });
    render(<TrackRecordPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not load the track record/);
    expect(screen.queryByTestId('scored-accuracy')).not.toBeInTheDocument();
  });

  it('marks which direction is better rather than leaving a signed number bare', async () => {
    render(<TrackRecordPage />);

    const served = await screen.findByTestId('served-accuracy');
    const ordinary = within(served).getByRole('row', { name: /all hours/ });
    const giant = within(served).getByRole('row', { name: /6 m and above/ });

    // The finding #52 corrected: worse on ordinary days, still decisively better on the
    // big ones. A page that lost the sign here would report the opposite of both.
    expect(within(ordinary).getByText('−0.077m')).toHaveClass('worse');
    expect(within(giant).getByText('+0.356m')).toHaveClass('better');
  });
});

describe('caveats that travel with a figure', () => {
  it('shows the qualification under the table, not as a marker to chase', async () => {
    // Both caveated rows are figures that read as stronger than they are — the headline
    // Gold Day comparison, and the one aggregate whose sign does not survive #52's
    // sensitivity check. A footnote a reader has to go and find is a footnote that failed.
    render(<TrackRecordPage />);

    const scored = await screen.findByTestId('scored-accuracy');
    const served = screen.getByTestId('served-accuracy');

    expect(within(scored).getByText(/120 hours across only 5 Gold Days/)).toBeInTheDocument();
    expect(
      within(served).getByText(/Not robust to the reconstruction assumption/),
    ).toBeInTheDocument();
  });

  it('does not put a note against a row that does not have one', async () => {
    render(<TrackRecordPage />);

    const scored = await screen.findByTestId('scored-accuracy');
    const notes = within(scored).getAllByRole('listitem');

    expect(notes).toHaveLength(1);
    expect(notes[0]).toHaveTextContent('Gold Day hours');
  });
});

describe('the two tiers', () => {
  it('reports Watch and Go Call separately, never as one figure', async () => {
    render(<TrackRecordPage />);

    const heldOut = await screen.findByTestId('panel-held-out');

    expect(
      within(within(heldOut).getByLabelText('Go Call')).getByText('9 of 13'),
    ).toBeInTheDocument();
    expect(
      within(within(heldOut).getByLabelText('Watch')).getByText('12 of 13'),
    ).toBeInTheDocument();
  });

  it('shows what each tier cost beside what it caught', async () => {
    // A tier catching 12 of 13 sounds excellent until you learn it flagged 193 days to do
    // it. Showing the first without the second is the flattering half of a two-part fact.
    render(<TrackRecordPage />);

    const heldOut = await screen.findByTestId('panel-held-out');
    const watch = within(heldOut).getByLabelText('Watch');

    expect(within(watch).getByText('193')).toBeInTheDocument();
    expect(within(watch).getByText(/32\.2 per Big-Wave Season/)).toBeInTheDocument();
  });

  it('states a tier’s wasted days as a share of the days it flagged, not the reverse', async () => {
    // `days_flagged` was asserted on its own, so the pair in the waste row could be
    // swapped without moving it — "at most 193 of 181", a subset larger than the set it
    // is drawn from. Nonsense on its face, and nothing on the page objected.
    const tier = trackRecord.held_out.watch_or_better;

    render(<TrackRecordPage />);

    const heldOut = await screen.findByTestId('panel-held-out');
    const watch = within(heldOut).getByLabelText('Watch');

    expect(
      within(watch).getByText(`at most ${tier.days_wasted_upper_bound} of ${tier.days_flagged}`),
    ).toBeInTheDocument();
  });

  it('keeps the held-out panel and the whole record apart', async () => {
    // Averaging them would give a reader neither: one is measured on seasons the
    // thresholds never saw, the other partly on the seasons they were chosen against.
    // Asserted per panel rather than per page: both spans appear in the introduction too,
    // so a page-wide text query would pass on a page that rendered one panel twice.
    render(<TrackRecordPage />);

    const heldOut = await screen.findByTestId('panel-held-out');
    const whole = screen.getByTestId('panel-full-record');

    expect(within(heldOut).getByText(trackRecord.held_out.span)).toBeInTheDocument();
    expect(within(whole).getByText(trackRecord.full_record.span)).toBeInTheDocument();
    expect(
      within(within(whole).getByLabelText('Go Call')).getByText('16 of 38'),
    ).toBeInTheDocument();
  });
});

describe('the wasted-trip figure', () => {
  it('states how often acting on a Go Call would have been wasted', async () => {
    render(<TrackRecordPage />);

    const statement = await screen.findByTestId('waste-statement');

    expect(statement).toHaveTextContent('at most 34 of 43 trips');
    expect(statement).toHaveTextContent('79%');
  });

  it('says how many Go Calls landed on a confirmed giant day, not how many did not', async () => {
    // The sentence carries two counts out of the same tier, and only the wasted one was
    // asserted. Rendering `days_wasted_upper_bound` where `gold_days_called` belongs makes
    // the page say 34 of 43 Go Calls landed on a confirmed giant day — when the answer is
    // 9, and the very next clause says at most 34 of those 43 were wasted. The page
    // contradicts itself in two adjacent sentences, in the flattering direction, and every
    // test passed.
    const goCall = trackRecord.held_out.go_call;

    render(<TrackRecordPage />);

    const statement = await screen.findByTestId('waste-statement');

    expect(statement.textContent).toContain(`${goCall.gold_days_called} of them landed`);
  });

  it('says the figure is a worst case and why', async () => {
    // The hand-verified list is not a census, so a flagged day absent from it may still
    // have been giant. Quoting the number without that turns a bound into a measurement.
    render(<TrackRecordPage />);

    const statement = await screen.findByTestId('waste-statement');

    expect(statement).toHaveTextContent(/At most, because/);
    expect(statement).toHaveTextContent(/can only be kinder/);
  });
});

describe('what it refuses to leave out', () => {
  it('states that these are reconstructed calls before showing any figure', async () => {
    render(<TrackRecordPage />);

    const caveat = await screen.findByTestId('basis-caveat');

    expect(caveat).toHaveTextContent(/not a live record/);
    expect(caveat).toHaveTextContent(trackRecord.held_out.basis);
  });

  it('states how few confirmed giant days the whole thing rests on', async () => {
    render(<TrackRecordPage />);

    expect(await screen.findByTestId('gold-day-total')).toHaveTextContent('38');
    expect(screen.getByTestId('limitations')).toHaveTextContent(
      'The whole calibration rests on 38 confirmed days.',
    );
  });

  it('says which confirmed days chose the thresholds and which were held back', async () => {
    // Only the total was pinned, leaving the split free to reverse: a 25/13 record reading
    // "13 were used to choose the thresholds, which leaves 25 the system had never seen"
    // nearly doubles the unseen days, which is the one number on this page a sceptical
    // reader would go to first. Each count is tied to its own clause.
    render(<TrackRecordPage />);

    const paragraph = (await screen.findByTestId('gold-day-total')).closest('p')!;

    expect(paragraph.textContent).toContain(`${trackRecord.gold_days_fitted} were used to choose`);
    expect(paragraph.textContent).toContain(
      `${trackRecord.gold_days_validated} the system had never seen`,
    );
  });

  it('introduces the page with the whole record’s span, not the held-out one', async () => {
    // The two spans are asserted inside their own panels, and the lead sentence naming one
    // of them was covered by neither. It promises what follows covers the whole record, so
    // quietly narrowing it to the held-out years describes a different page than the one
    // below it.
    render(<TrackRecordPage />);

    const lead = await screen.findByText(/here is what the system would have said/);

    expect(lead).toHaveTextContent(trackRecord.full_record.span);
    expect(lead).not.toHaveTextContent(trackRecord.held_out.span);
  });

  it('lists the days most recent first, as its own caption promises', async () => {
    // The caption says "most recent first" and nothing checked it, so dropping the reverse
    // left the table in the record's own order — oldest first — under a caption asserting
    // the opposite. Every row is found by date elsewhere in this suite, which is exactly
    // why order went unnoticed.
    render(<TrackRecordPage />);

    const table = await screen.findByTestId('day-record');
    const dates = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('rowheader')[0]?.textContent ?? '');

    expect(dates).toEqual([...dates].sort().reverse());
    // And that this is a real ordering rather than a table of one row, or of equal dates.
    expect(new Set(dates).size).toBe(trackRecord.days.length);
  });

  it('explains the gap between what it predicts and the height of a wave face', async () => {
    // The distinction CLAUDE.md calls load-bearing, in the one place a reader without a
    // background in this would otherwise assume the news figure is what is being promised.
    render(<TrackRecordPage />);

    const limitations = await screen.findByTestId('limitations');

    expect(limitations).toHaveTextContent(/does not predict the height of a wave face/);
    expect(limitations).toHaveTextContent(/cannot be converted from this by any fixed ratio/);
    expect(limitations).toHaveTextContent(/mooring 15km offshore/);
  });

  it('says the height column is the call input, not the outcome', async () => {
    // A column headed "peak height" next to one headed "what it called" implies the second
    // was checked against the first. It was not: both come from the same reconstruction, and
    // the only independently verified column is the last one.
    render(<TrackRecordPage />);

    const caveat = await screen.findByTestId('day-record-caveat');

    expect(caveat).toHaveTextContent('The height column is not an outcome.');
    expect(caveat).toHaveTextContent(/same reconstruction the call was made from/);
  });

  it('shows the confirmed giant days it missed, not only the ones it caught', async () => {
    render(<TrackRecordPage />);

    const table = await screen.findByTestId('day-record');
    const missed = trackRecord.days.find((day) => day.gold_day && day.call === 'none')!;
    const row = within(table).getByRole('row', { name: new RegExp(missed.date) });

    expect(within(row).getByText('No call')).toBeInTheDocument();
    expect(within(row).getByText(/Yes \(ratified\)/)).toBeInTheDocument();
  });

  it('names where the numbers came from, so a reader can check them', async () => {
    render(<TrackRecordPage />);

    expect(await screen.findByTestId('record-provenance')).toHaveTextContent(trackRecord.source);
  });
});

describe('the live record', () => {
  it('says plainly when nothing has been issued for real', async () => {
    render(<TrackRecordPage />);

    const issued = await screen.findByTestId('issued-record');

    expect(issued).toHaveTextContent('Nothing yet.');
    expect(issued).toHaveTextContent(/none of it is an operating history/);
  });

  it('counts real calls without claiming any of them were right', async () => {
    // No buoy reading reaches the running system, so there is nothing to score a stored
    // call against. Counting is the honest limit of what this section can say, and the
    // page has to say so rather than let a count read as a record of success.
    serve({
      issued: {
        calls_issued: 42,
        dates_covered: 9,
        go_calls_issued: 3,
        first_issued_at: '2026-08-01T06:00:00+00:00',
        last_issued_at: '2026-08-04T06:00:00+00:00',
      },
    });
    render(<TrackRecordPage />);

    const issued = await screen.findByTestId('issued-record');

    expect(issued).toHaveTextContent('42');
    expect(issued).toHaveTextContent('None of them are scored here.');
    expect(issued).toHaveTextContent(/No buoy reading reaches the running system/);
  });

  it('distinguishes an unreadable record from an empty one', async () => {
    // Null is an absence of knowledge; zero is a fact about this installation. Reporting the
    // unreadable case as zero would invent the more flattering of the two — a clean record
    // rather than one nobody could open. The rest of the page must survive it.
    serve({ issued: null });
    render(<TrackRecordPage />);

    const issued = await screen.findByTestId('issued-record');

    expect(issued).toHaveTextContent('Not known.');
    expect(issued).not.toHaveTextContent('Nothing yet.');
    expect(screen.getByTestId('scored-accuracy')).toBeInTheDocument();
  });
});

describe('failure', () => {
  it('says the record could not be loaded rather than rendering an empty section', async () => {
    // A blank track record is indistinguishable from a system with nothing to show for
    // itself, and the silent version is the flattering one.
    server.use(http.get('*/api/track-record', () => HttpResponse.json({}, { status: 500 })));
    render(<TrackRecordPage />);

    const alert = await screen.findByRole('alert');

    expect(alert).toHaveTextContent(/Could not load the track record/);
    expect(alert).toHaveTextContent(/should be read as an absence of failures/);
  });
});
