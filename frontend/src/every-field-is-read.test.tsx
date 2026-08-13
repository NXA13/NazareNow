/**
 * Every field the backend sends is either read by the page or declared unread, on the record.
 *
 * Ticket #102. Twice now the same defect has shipped: a value fetched, typed in `api.ts`,
 * mocked in `handlers.ts` and then dropped on the floor, with the whole suite green.
 * `ForecastHour.wind_direction` was in every hour and rendered nowhere (#98); `EarlierCall`
 * arrived four runs deep and `Shift` read `at(-1)` (#99). Deleting either from the backend
 * response would have failed nothing. Two rounds of spot-checking missed both, and the sweep
 * that found them found them in the same blind spot — so this is a guard rather than a third
 * sweep.
 *
 * **The mechanism is a mutation, not a matcher.** Each field is given a different value, the
 * page is rendered again, and the markup is compared with the baseline. A field the registry
 * calls read must change the page; a field it calls unread must leave it byte-identical.
 * Nothing here asserts *where* a value should appear or *how* it should be formatted — the
 * suites next door do that, and doing it twice would make this file break every time a
 * sentence was reworded.
 *
 * **Both branches cost the same, which is the point.** A registry whose "not read" arm were a
 * free-text sentence would accumulate free-text sentences; here it is a claim about the
 * rendered page, and it fails the moment somebody renders the field and forgets this file.
 *
 * **A mutated fixture is deliberately incoherent, and that is the mechanism rather than a
 * lapse.** The *baseline* is a response the backend could produce, and has to be. What is
 * mutated off it is one field, alone: hours whose swell no longer matches the day card derived
 * from them, a Lead Time that no longer agrees with the stamp beside it, an hour dated past the
 * day `days.py` grouped it under. Propagating a change into the fields that echo it is
 * precisely what would make this file pass for the wrong reason — the page would differ
 * because the *day card* moved, and the hour would go on being unread. So the plausibility bar
 * here is on the baseline and on the shape of each value, never on agreement between fields.
 *
 * **The registries are exhaustive by type, not by diligence.** `Registry<T>` maps over every
 * key of `T`, so `tsc --noEmit` — a CI step — fails the build when the backend grows a field
 * nobody has decided about yet. The compiler makes the decision unavoidable; the mutation
 * makes the answer honest.
 *
 * **What this does not cover, so nothing reads it as covering more.** Two of the wire's types:
 * `ForecastHour` and `EarlierCall`, the two the defect happened to. `DayCall`, `ForecastDay`,
 * `DaySpread`, `Forecast` and the whole track-record tree are not in it. Neither is
 * `CurrentConditions`, which matters more than the rest of that list: `ForecastHour` is
 * literally an `Omit` of it, so a reader could take its ten readings for guarded. They are not
 * — the current panel lives in `App.tsx` and nothing here renders it. Nor is this finer than
 * one field: a field whose *unit* alone went unread would still pass.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import type { CallStatus, EarlierCall, ForecastDay, ForecastHour, Reading } from './api';
import { ForecastRange } from './Forecast';
import { forecast } from './test/handlers';
import { server } from './test/server';

/** What the page does with one field the backend sends, and the proof of it. */
interface WireField<T> {
  /** Whether anything a reader can see depends on this field's value. Verified, never trusted. */
  read: boolean;
  /** How it reaches a reader — or, when `read` is false, why nothing shows it. */
  note: string;
  /** A different value for this field, on its own. */
  other: (sent: T) => T;
}

/** Every field of `T`, with no way to omit one.
 *
 * `-?` strips optionality, so a field the wire marks optional still has to be decided about
 * rather than slipping in under a `?`. `TierRecord.delivered` over in `api.ts` is what one of
 * those looks like when it arrives. */
type Registry<T> = { [K in keyof T]-?: WireField<T[K]> };

/** One registry entry as the driver below reads it.
 *
 * The per-field types are enforced where each registry is declared, which is where a wrong
 * mutation would actually be written. The loop needs only a name, a verdict and a function. */
interface Decision {
  read: boolean;
  note: string;
  other: (sent: never) => unknown;
}

function decisions<T>(registry: Registry<T>): [string, Decision][] {
  return Object.entries(registry);
}

/** One field replaced on a copy of a record, leaving everything else alone.
 *
 * The result is asserted rather than inferred: a computed key widens the spread to an index
 * signature, and the registry above is where the field's own type is actually checked. */
function replace<T extends object>(item: T, field: string, other: Decision['other']): T {
  return { ...item, [field]: other(item[field as keyof T] as never) } as T;
}

/** The smallest difference `formatValue` can show, which rounds to two decimals. */
const DISPLAYED = 0.01;

/**
 * Something moved, and everything that moved moved far enough for a reader to see it.
 *
 * Asserting only that the mutated fixture differs is not enough, and the hole it leaves is the
 * escape hatch reopened two decimal places down: a `read: false` entry whose `other` adds
 * 0.001 renders an identical page, so a genuinely rendered field is certified unread and the
 * whole file goes green. #102 asks for the mutation to differ "by more than the rounding the
 * page displays at" — this is that, walked over whatever shape the field happens to have.
 *
 * A leaf that did not move is fine. A unit that stayed put while its value changed is the
 * ordinary case, not a failure.
 */
function moved(sent: unknown, changed: unknown, path: string): boolean {
  if (typeof sent === 'number' && typeof changed === 'number') {
    if (sent === changed) return false;
    expect(
      Math.abs(changed - sent),
      `${path} moved by less than the page can show, so an unread verdict would be meaningless`,
    ).toBeGreaterThanOrEqual(DISPLAYED);
    return true;
  }

  if (
    sent !== null &&
    changed !== null &&
    typeof sent === 'object' &&
    typeof changed === 'object'
  ) {
    const keys = new Set([...Object.keys(sent), ...Object.keys(changed)]);
    let any = false;
    for (const key of keys) {
      const before = (sent as Record<string, unknown>)[key];
      const after = (changed as Record<string, unknown>)[key];
      if (moved(before, after, `${path}.${key}`)) any = true;
    }
    return any;
  }

  return sent !== changed;
}

const QUIET = forecast.days[0]!;
const BIG = forecast.days[1]!;
const EASING = forecast.days[2]!;
const BIG_CALL = BIG.call!;

/**
 * Everything the forecast range draws with one day open, as markup.
 *
 * The comparison is the whole rendered subtree rather than a chosen element, because the
 * question is whether the value reaches a reader *anywhere* — pinning it to the hourly table
 * would let a field that moved to a caption or an `aria-label` read as dropped.
 */
async function pageFor(day: ForecastDay): Promise<string> {
  server.use(
    http.get('*/api/conditions/forecast', () =>
      HttpResponse.json({ ...forecast, days: [QUIET, day, EASING] }),
    ),
  );

  const view = render(<ForecastRange />);
  await userEvent.click(await screen.findByRole('button', { name: new RegExp(day.date) }));
  // The table itself, and nothing inside it. Waiting on a testid that one of these tickets
  // introduced would couple the harness to the defect it guards: reverting #98 as shipped —
  // the wind cell *and* the note under the table — timed out all sixteen tests instead of
  // failing `wind_direction` alone, which is a broken suite rather than a caught bug.
  await screen.findByRole('table');

  const html = view.container.innerHTML;
  view.unmount();
  return html;
}

/**
 * The verdict, applied identically on both sides of this file.
 *
 * One function because the `EarlierCall` loop once asserted that the page had changed
 * *unconditionally*, while its registry carried a `read` flag nobody consulted — half the file
 * verifying a claim the other half took on trust, under a field documented as "verified, never
 * trusted". A `read: false` entry there would have been asserted read.
 */
async function holdToVerdict(
  spec: Decision,
  sent: unknown,
  changed: unknown,
  day: ForecastDay,
  baseline: string,
): Promise<void> {
  expect(moved(sent, changed, spec.note)).toBe(true);

  const after = await pageFor(day);

  if (spec.read) {
    expect(after).not.toEqual(baseline);
  } else {
    expect(after).toEqual(baseline);
  }
}

/** The same reading in the unit a provider could switch to. `Reading` carries its unit
 * precisely because that happens, and a page reading the value past the unit is the failure
 * those fields exist to make visible. */
const feet = (r: Reading): Reading => ({
  value: Number((r.value * 3.28084).toFixed(2)),
  unit: 'ft',
});
const fahrenheit = (r: Reading): Reading => ({
  value: Number((r.value * 1.8 + 32).toFixed(2)),
  unit: '°F',
});
const mph = (r: Reading): Reading => ({
  value: Number((r.value * 0.621371).toFixed(2)),
  unit: 'mph',
});

/** Two compass sectors round: far enough that `compassPoint` names a different one, near
 * enough to be a different swell rather than an impossible one. */
const veer = (r: Reading): Reading => ({ ...r, value: (r.value + 45) % 360 });

/** Seconds have no alternative a provider would report in, so the value alone moves. */
const longer = (r: Reading): Reading => ({ ...r, value: Number((r.value + 3).toFixed(2)) });

describe('ForecastHour', () => {
  /**
   * What the hourly table does with each of the eleven fields an hour carries.
   *
   * Six are read and five are not. Writing those five sentences is the whole value of this
   * registry, and it is where `wind_direction` stood out: `CONTEXT.md` defines Offshore
   * Conditions as five quantities, the table renders those five, and the Combined Sea and the
   * temperatures are shown only for *now*, in `App.tsx`'s panel above the forecast. Each of
   * the five below has an honest sentence. `wind_direction` belonged with the six and never
   * had one.
   */
  const fields: Registry<ForecastHour> = {
    at: {
      read: true,
      note: 'the row heading, sliced out of the stamp',
      // Shifted an hour on, which rolls the last stamp past the date `days.py` grouped the
      // day under — an incoherence, and an unavoidable one. Within a Nazaré day the 24 hourly
      // stamps are fully determined: `group_by_date` keys on `at[:10]` and the provider is
      // hourly, so there is no *other* value this field could hold and still belong to this
      // day. What the shift proves is that the heading is read off the stamp rather than off
      // the row's position, and no coherent fixture can prove that.
      other: (at) => shiftHours(at, 1),
    },
    swell_height: {
      read: true,
      note: 'the swell column',
      other: feet,
    },
    swell_period: {
      read: true,
      note: 'the period column',
      other: longer,
    },
    swell_direction: {
      read: true,
      note: 'the swell direction column, as a compass point',
      other: veer,
    },
    significant_wave_height: {
      read: false,
      note:
        'not a column. The panel above states a significant wave height for the *day*, which ' +
        'the Amplification Model has had its say on; this is the provider’s own figure for ' +
        'the hour. Two numbers of the same name on one screen, which a reader would ' +
        'reasonably expect to match.',
      other: feet,
    },
    wave_period: {
      read: false,
      note: 'not a column. The table is the Swell story, and this is the Combined Sea’s period.',
      other: longer,
    },
    wave_direction: {
      read: false,
      note: 'not a column, for the reason `wave_period` is not one.',
      other: veer,
    },
    water_temperature: {
      read: false,
      note:
        'not a column. It is shown for now, in the panel above the forecast, and no call ' +
        'turns on it — an hourly ladder of it would widen the table without answering story 6.',
      other: fahrenheit,
    },
    air_temperature: {
      read: false,
      note: 'not a column, for the reason `water_temperature` is not one.',
      other: fahrenheit,
    },
    wind_speed: {
      read: true,
      note: 'the wind column',
      other: mph,
    },
    wind_direction: {
      read: true,
      note: 'the bearing inside the wind cell (#98)',
      other: veer,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await pageFor(BIG);
      // Only the hours move; the day's own summaries are left stale on purpose. Rebuilding
      // them would change the card above the table too, and the page would then differ for a
      // reason that says nothing about whether the *hour* was read.
      const changed = { ...BIG, hours: BIG.hours.map((hour) => replace(hour, name, spec.other)) };

      await holdToVerdict(spec, BIG.hours, changed.hours, changed, baseline);
    });
  }
});

/** A stamp moved by whole hours, keeping the naive shape the wire uses.
 *
 * Arithmetic on the parts rather than through `Date`: the hours arrive already in Nazaré's own
 * zone — the Pipeline Run asks the provider for `Europe/Lisbon` and checks it got it, which is
 * ADR 0008 and why `days.py` can slice the date off the front — so they carry no offset, and
 * putting one through `new Date` would apply the test runner's. */
function shiftHours(at: string, by: number): string {
  const day = Number(at.slice(8, 10));
  const hour = Number(at.slice(11, 13));
  const clock = hour + by;
  const rolled = day + Math.floor(clock / 24);
  return `${at.slice(0, 8)}${String(rolled).padStart(2, '0')}T${String(((clock % 24) + 24) % 24).padStart(2, '0')}:00`;
}

describe('EarlierCall', () => {
  /**
   * Four superseded runs about one date, which is what `recent_calls` sends at its default
   * bound of five.
   *
   * **Coherent with the call they sit under, which took a correction to get right.** `BIG_CALL`
   * speaks at 4 days out about 2026-02-13, so the run that issued it spoke on the 9th and every
   * run behind it spoke earlier and further out. A series stamped later than the call it
   * precedes is not a fixture the backend can produce, and this file has no business asserting
   * anything about impossible input.
   *
   * **Lead Times repeat, deliberately.** Pipeline Runs are three-hourly (`cycle.py`) while
   * `lead_time_days` is a whole number of days, so consecutive runs about one date routinely
   * share one — which is what makes the stamp, and not the Lead Time, the thing that orders
   * these rows. `Forecast.test.tsx` builds its series the same way, and #99 was caught
   * building the impossible version.
   */
  function run(issued: string, lead: number, value: number): EarlierCall {
    return {
      issued_at: issued,
      lead_time_days: lead,
      status: 'watch',
      predicted_significant_wave_height: { value, unit: 'm' },
      plausible_range: { low: value - 0.9, high: value + 1.3, unit: 'm' },
    };
  }

  const RUNS: EarlierCall[] = [
    run('2026-02-07T00:00:00Z', 6, 4.1),
    run('2026-02-07T12:00:00Z', 6, 5.2),
    run('2026-02-08T00:00:00Z', 5, 6.1),
    run('2026-02-08T12:00:00Z', 5, 6.2),
  ];

  const dayWith = (runs: EarlierCall[]): ForecastDay => ({
    ...BIG,
    call: {
      ...BIG_CALL,
      predicted_significant_wave_height: { value: 6.4, unit: 'm' },
      previous_runs: runs,
    },
  });

  /** What the series does with each of the five fields a superseded call carries.
   *
   * All five are read, and every one of them was read only on the most recent run until #99. */
  const fields: Registry<EarlierCall> = {
    issued_at: {
      read: true,
      note: 'the date on each row, which is what orders a series of repeating Lead Times',
      // Six hours later, which is the one shift that leaves every run on the date its Lead
      // Time was measured from, still ascending, and still behind the run held still below.
      other: (at) => new Date(new Date(at).getTime() + 6 * 3_600_000).toISOString(),
    },
    lead_time_days: {
      read: true,
      note: 'how far out each run spoke',
      // Up, so the series still falls as the date approaches. It no longer agrees with the
      // stamp beside it, which is what mutating one field of a pair always costs.
      other: (days) => days + 2,
    },
    status: {
      read: true,
      note: 'the tier badge on each row',
      // A date newly raised to a Watch, rather than one that flickered between tiers.
      other: () => 'none' as CallStatus,
    },
    predicted_significant_wave_height: {
      read: true,
      note: 'the height on each row, and the shape the bar draws from them',
      other: (r) => ({ ...r, value: Number((r.value + 1.7).toFixed(2)) }),
    },
    plausible_range: {
      read: true,
      note: 'the range beside each height',
      // Nullable on the wire and never null here: a series mixing calls that carry a range
      // with calls that do not is `Forecast.test.tsx`'s case, and it asserts the wording.
      other: (range) => range && { ...range, low: range.low - 0.8, high: range.high + 0.8 },
    },
  };

  for (const [name, spec] of decisions(fields)) {
    const what = spec.read ? 'read on every run, not only the last' : 'not read';
    it(`${name} is ${what} — ${spec.note}`, async () => {
      const baseline = await pageFor(dayWith(RUNS));
      // The most recent run is left alone deliberately. `Shift` reads `at(-1)` and always
      // did; holding it still means any difference below comes from the runs behind it,
      // which is precisely the distinction #99 turned on. Mutating the whole list lets the
      // shipped-before-#99 page pass three of these five.
      const changed = RUNS.map((sent, index) =>
        index === RUNS.length - 1 ? sent : replace(sent, name, spec.other),
      );

      await holdToVerdict(spec, RUNS, changed, dayWith(changed), baseline);
    });
  }
});
