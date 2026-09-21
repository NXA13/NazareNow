/**
 * What the map says about the age of the wind it is drawing (#139).
 *
 * The darts themselves are `Wind.test.tsx`'s, and the sea floor and the crests are
 * `Bathymetry.test.tsx`'s. What is left for this file is the slot's own prose: the sentences
 * that qualify the picture rather than draw it.
 *
 * **The gap this closes.** `/api/conditions/grid` dates the grid by its own fetch, and a run
 * whose grid fetch failed is still a success — so the wind on this map could be two cycles old
 * beside a forecast that arrived minutes ago, and the map said nothing at all. #142 gave the
 * endpoint `refresh_failed`, a reported fact rather than an inference from a clock, and this is
 * the half that reaches a reader.
 *
 * **Two questions, two clauses, never folded together.** ADR 0018's whole argument is that
 * *how old is this* and *did the last attempt fail* are answered from different kinds of
 * evidence and can disagree — `refresh_failed` can be true while `stale` is still false, which
 * is the point of it. A note that printed one sentence for both would throw that away, so each
 * is its own clause and each is asserted alone.
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MapSlot } from './MapSlot';
import { conditionsGrid } from './test/handlers';
import type { ConditionsGrid } from './api';

const GRID = conditionsGrid as unknown as ConditionsGrid;

function slotFor(grid: Partial<ConditionsGrid>) {
  return render(<MapSlot swell={null} grid={{ ...GRID, ...grid }} windUnavailable={false} />);
}

describe('how old the map says its wind is', () => {
  it('says nothing at all when the grid is current', () => {
    // The shipped fixture is a healthy grid, and a note that appeared on a healthy grid would
    // be the "warning nobody reads" `cycle.py` refuses to train people into.
    const { queryByRole } = slotFor({ stale: false, refresh_failed: false });
    expect(queryByRole('status')).toBeNull();
  });

  it('says a refresh was lost, inside one cycle, while the grid is still not stale', () => {
    // The whole of #139: `stale` is false here — six hours have not passed — and the reader is
    // told anyway, because the run recorded the failure the instant it happened.
    const { getByRole } = slotFor({ stale: false, refresh_failed: true });
    expect(getByRole('status')).toHaveTextContent(/refresh since then failed/i);
  });

  it('names when the wind it is drawing arrived', () => {
    // A failure with no stamp beside it cannot be acted on: "a refresh failed" is a different
    // sentence at ten minutes old and at five hours old.
    const { getByRole } = slotFor({ stale: false, refresh_failed: true });
    expect(getByRole('status').querySelector('time')).toHaveAttribute('dateTime', GRID.fetched_at);
  });

  it('reports a stale grid even when no refresh is on record as having failed', () => {
    // Reachable, and not the same fault: a pipeline that stopped running altogether records no
    // failures at all, so `refresh_failed` stays false while the wind ages past six hours.
    const { getByRole } = slotFor({ stale: true, refresh_failed: false });
    const note = getByRole('status');
    expect(note).toHaveTextContent(/nothing newer has arrived for at least 6 hours/i);
    expect(note).not.toHaveTextContent(/refresh since then failed/i);
  });

  it('counts the hours the endpoint served rather than a copy of the threshold', () => {
    // `STALE_AFTER_HOURS` lives in `cycle.py`. A 6 hard-coded here is a fourth place for it to
    // go stale in, which is the habit `MapSlot.tsx` already names.
    const { getByRole } = slotFor({ stale: true, refresh_failed: false, stale_after_hours: 9 });
    expect(getByRole('status')).toHaveTextContent(/at least 9 hours/i);
  });

  it('says both when both are true, because they are two different facts', () => {
    const note = slotFor({ stale: true, refresh_failed: true }).getByRole('status');
    expect(note).toHaveTextContent(/nothing newer has arrived for at least 6 hours/i);
    expect(note).toHaveTextContent(/refresh since then failed/i);
  });

  it('does not call a wind it never drew out of date', () => {
    // No darts are on the page, so "this wind is out of date" would be qualifying a picture
    // that is not there. The missing sentence is the one that belongs, and only that one.
    const { getByText, queryByRole } = render(
      <MapSlot
        swell={null}
        grid={{ ...GRID, points: [], stale: true, refresh_failed: true }}
        windUnavailable={false}
      />,
    );
    expect(getByText(/wind unavailable/i)).toBeInTheDocument();
    expect(queryByRole('status')).toBeNull();
  });
});
