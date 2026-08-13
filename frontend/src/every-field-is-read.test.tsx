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
 * **The mechanism is a mutation, not a matcher.** Each field is given a different value the
 * backend could plausibly have sent, the page is rendered again, and the markup is compared
 * with the baseline. A field the registry calls read must change the page; a field it calls
 * unread must leave it byte-identical. Nothing here asserts *where* a value should appear or
 * *how* it should be formatted — the suites next door do that, and doing it twice would make
 * this file break every time a sentence was reworded.
 *
 * **Both branches cost the same, which is the point.** A registry whose "not read" arm were a
 * free-text sentence would accumulate free-text sentences; here it is a claim about the
 * rendered page, and it fails the moment somebody renders the field and forgets this file.
 *
 * **The registries are exhaustive by type, not by diligence.** `Registry<T>` maps over every
 * key of `T`, so `tsc --noEmit` — a CI step — fails the build when the backend grows a field
 * nobody has decided about yet. The compiler makes the decision unavoidable; the mutation
 * makes the answer honest.
 *
 * **What this does not cover, so nothing reads it as covering more.** Two of the wire's types:
 * `ForecastHour` and `EarlierCall`, the two the defect happened to. `DayCall`, `ForecastDay`,
 * `DaySpread`, `Forecast` and the whole track-record tree are not in it. Nor is it finer than
 * one field: a `Reading` is mutated in its value and, where the provider has a real
 * alternative, its unit — but a field whose *unit* alone went unread would still pass, and no
 * such failure has occurred.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import type { CallStatus, EarlierCall, ForecastDay, ForecastHour } from './api';
import { ForecastRange } from './Forecast';
import { forecast } from './test/handlers';
import { server } from './test/server';

/** What the page does with one field the backend sends, and the proof of it. */
interface WireField<T> {
  /** Whether anything a reader can see depends on this field's value. Verified, never trusted. */
  read: boolean;
  /** How it reaches a reader — or, when `read` is false, why nothing shows it. */
  note: string;
  /** A different value the backend could plausibly have sent for this field instead. */
  other: (sent: T) => T;
}

/** Every field of `T`, with no way to omit one.
 *
 * `-?` strips optionality so a field the wire marks optional still has to be decided about:
 * `TierRecord.delivered` is the kind of field that arrives later and would otherwise slip in
 * under a `?`. */
type Registry<T> = { [K in keyof T]-?: WireField<T[K]> };

/** A registry as the driver below reads one.
 *
 * The per-field types are enforced where each registry is declared, which is where a wrong
 * mutation would actually be written. The loop needs only a name, a verdict and a function, so
 * it takes one cast here rather than threading a generic through every call. */
interface Decision {
  read: boolean;
  note: string;
  other: (sent: never) => unknown;
}

type Decisions = Record<string, Decision>;

function decisionsOf<T>(registry: Registry<T>): Decisions {
  return registry;
}

/** One field replaced on a copy of a record, leaving everything else alone.
 *
 * The result is asserted rather than inferred: a computed key widens the spread to an index
 * signature, and the registry above is where the field's own type is actually checked. */
function replace<T extends object>(item: T, field: string, other: Decision['other']): T {
  return { ...item, [field]: other(item[field as keyof T] as never) } as T;
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
  // Waited on explicitly: the hourly table is the half of the panel this file exists for, and
  // reading the markup before it mounted would compare two loading states and call every
  // field unread.
  await screen.findByTestId('wind-direction-note');

  const html = view.container.innerHTML;
  view.unmount();
  return html;
}

/** A stamp moved by whole hours, keeping the naive shape the wire uses.
 *
 * Arithmetic on the parts rather than through `Date`, because `handlers.ts` sends hours with
 * no zone on them and putting one through `new Date` would apply the runner's. */
function shiftHours(at: string, by: number): string {
  const day = Number(at.slice(8, 10));
  const hour = Number(at.slice(11, 13));
  const moved = hour + by;
  const rolled = day + Math.floor(moved / 24);
  const clock = ((moved % 24) + 24) % 24;
  return `${at.slice(0, 8)}${String(rolled).padStart(2, '0')}T${String(clock).padStart(2, '0')}:00`;
}

describe('ForecastHour', () => {
  /**
   * What the hourly table does with each of the eleven fields an hour carries.
   *
   * Five are unread and one was not, which is the asymmetry this file was written around.
   * `CONTEXT.md` defines Offshore Conditions as five quantities and the table renders those
   * five; the Combined Sea and the temperatures arrive hourly and are shown only for *now*,
   * in the panel above the forecast. Each has a sentence below. `wind_direction` never had
   * one, and writing these is where that shows.
   */
  const fields: Registry<ForecastHour> = {
    at: {
      read: true,
      note: 'the row heading, sliced out of the stamp',
      // A block shifted an hour on, rolling past midnight. That is a shape the backend
      // genuinely produces: under summer time a Nazaré day is UTC+1 (ADR 0008), so its hours
      // straddle two UTC dates. February keeps the roll inside the month.
      other: (at) => shiftHours(at, 1),
    },
    swell_height: {
      read: true,
      note: 'the swell column',
      // Feet, not just a larger number. `Reading` carries its unit precisely because a
      // provider can switch, and that is the change most likely to be read past.
      other: (r) => ({ value: Number((r.value * 3.28084).toFixed(2)), unit: 'ft' }),
    },
    swell_period: {
      read: true,
      note: 'the period column',
      // Seconds have no alternative the provider would report in, so the value alone moves.
      other: (r) => ({ ...r, value: Number((r.value + 3).toFixed(2)) }),
    },
    swell_direction: {
      read: true,
      note: 'the swell direction column, as a compass point',
      // 45° is two sectors: enough that `compassPoint` names a different one, small enough
      // to be a different swell rather than an impossible day.
      other: (r) => ({ ...r, value: (r.value + 45) % 360 }),
    },
    significant_wave_height: {
      read: false,
      note:
        'not a column. The Combined Sea forecast for the hour is the provider’s own figure, ' +
        'and the call above the table states a *fitted* significant wave height for the day — ' +
        'two numbers of the same name, one modelled raw and one corrected, on one screen.',
      other: (r) => ({ value: Number((r.value * 3.28084).toFixed(2)), unit: 'ft' }),
    },
    wave_period: {
      read: false,
      note: 'not a column. The table is the Swell story, and this is the Combined Sea’s period.',
      other: (r) => ({ ...r, value: Number((r.value + 3).toFixed(2)) }),
    },
    wave_direction: {
      read: false,
      note: 'not a column, for the reason `wave_period` is not one.',
      other: (r) => ({ ...r, value: (r.value + 45) % 360 }),
    },
    water_temperature: {
      read: false,
      note:
        'not a column. It is shown for now, in the panel above the forecast, and no call ' +
        'turns on it — an hourly ladder of it would widen the table without answering story 6.',
      other: (r) => ({ value: Number((r.value * 1.8 + 32).toFixed(2)), unit: '°F' }),
    },
    air_temperature: {
      read: false,
      note: 'not a column, for the reason `water_temperature` is not one.',
      other: (r) => ({ value: Number((r.value * 1.8 + 32).toFixed(2)), unit: '°F' }),
    },
    wind_speed: {
      read: true,
      note: 'the wind column',
      other: (r) => ({ value: Number((r.value * 0.621371).toFixed(2)), unit: 'mph' }),
    },
    wind_direction: {
      read: true,
      note: 'the bearing inside the wind cell (#98)',
      other: (r) => ({ ...r, value: (r.value + 45) % 360 }),
    },
  };

  for (const [name, spec] of Object.entries(decisionsOf(fields))) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await pageFor(BIG);
      // Only the hours move. Rebuilding the day's summaries from them would change the card
      // above the table too, and the page would differ for a reason that says nothing about
      // whether the *hour* was read — a false pass on every field here.
      const changed = { ...BIG, hours: BIG.hours.map((hour) => replace(hour, name, spec.other)) };

      // A mutation that does not mutate renders an identical page and marks every field
      // unread: the guard inverted, silently, with nothing red to show for it.
      expect(changed.hours).not.toEqual(BIG.hours);

      const after = await pageFor(changed);

      if (spec.read) {
        expect(after).not.toEqual(baseline);
      } else {
        expect(after).toEqual(baseline);
      }
    });
  }
});

describe('EarlierCall', () => {
  /**
   * Four superseded runs about one date, which is what `recent_calls` sends at its default
   * bound of five.
   *
   * Twelve hours apart and Lead Times that repeat, because Pipeline Runs are three-hourly
   * (`cycle.py`) while `lead_time_days` is a whole number of days — a series stepping one day
   * per run is spacing the pipeline cannot produce, and #99 was caught building exactly that.
   */
  const RUNS: EarlierCall[] = [
    run('2026-02-09T00:00:00Z', 8, 4.1),
    run('2026-02-09T12:00:00Z', 7, 5.2),
    run('2026-02-10T00:00:00Z', 7, 6.1),
    run('2026-02-10T12:00:00Z', 6, 6.2),
  ];

  function run(issued: string, lead: number, value: number): EarlierCall {
    return {
      issued_at: issued,
      lead_time_days: lead,
      status: 'watch',
      predicted_significant_wave_height: { value, unit: 'm' },
      plausible_range: { low: value - 0.9, high: value + 1.3, unit: 'm' },
    };
  }

  const dayWith = (runs: EarlierCall[]): ForecastDay => ({
    ...BIG,
    call: {
      ...BIG_CALL,
      predicted_significant_wave_height: { value: 6.4, unit: 'm' },
      previous_runs: runs,
    },
  });

  /**
   * What the series does with each of the five fields a superseded call carries.
   *
   * All five are read, and every one of them was read only on the most recent run until #99.
   */
  const fields: Registry<EarlierCall> = {
    issued_at: {
      read: true,
      note: 'the date on each row, which is what orders a series of repeating Lead Times',
      other: (at) => new Date(new Date(at).getTime() - 86_400_000).toISOString(),
    },
    lead_time_days: {
      read: true,
      note: 'how far out each run spoke',
      // Up, not down: the series still falls as the date approaches, which is the only shape
      // a real approach has.
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
      note: 'the range beside each height, or “no range recorded” where a run has none',
      other: (range) => range && { ...range, low: range.low - 0.8, high: range.high + 0.8 },
    },
  };

  for (const [name, spec] of Object.entries(decisionsOf(fields))) {
    it(`${name} is read on every run, not only the last — ${spec.note}`, async () => {
      const baseline = await pageFor(dayWith(RUNS));
      // The most recent run is left alone deliberately. `Shift` reads `at(-1)` and always
      // did; holding it still means any difference below comes from the runs behind it,
      // which is precisely the distinction #99 turned on. Mutating the whole list would let
      // the shipped-before-#99 page pass every field in this registry.
      const changed = RUNS.map((sent, index) =>
        index === RUNS.length - 1 ? sent : replace(sent, name, spec.other),
      );

      expect(changed).not.toEqual(RUNS);

      const after = await pageFor(dayWith(changed));

      expect(after).not.toEqual(baseline);
    });
  }
});
