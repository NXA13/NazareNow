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
 * **A field read inside a branch the baseline never enters reads as unread, so a baseline is
 * built to enter the branches the shipped fixture does not (#104).** The mechanism certifies
 * "unread" from a page that did not move, and a page cannot move on a field the render never
 * reached. `DayCall.model_agreement` is read only where `go_call_withheld` is true, and
 * `handlers.ts` withholds nothing — so on it a mutation of that field is invisible, and this
 * file would have written down the exact lie it exists to prevent. That is the escape hatch
 * again, one level up from the rounding one `moved` closes below. Where a gate is already open
 * on the shipped fixture the block says so rather than taking credit for it, because which gates
 * happen to be open is a property of `handlers.ts` that can change without this file being
 * touched.
 *
 * **Two components, one verdict.** `pageFor` draws the forecast range and `panelFor` draws the
 * whole app; both go through `holdToVerdict`, which is the only place in this file that decides
 * what a verdict costs. A second renderer must never mean a second standard.
 *
 * **Read is not the same as printed, and the difference is the point.**
 * `RangeCoverage.widening_factor` appears nowhere on the page and is read all the same: it is
 * the only thing that can decide whether the range's miss *grows* the further ahead the forecast
 * looks, and the clause that says so turns on it. A guard that went looking for values in the
 * markup would have called it dropped and invited somebody to delete it.
 *
 * **What this covers, and the one thing it still cannot say.** Every type the wire carries:
 * `Forecast`, `Calibration`, `DaySpread`, `CurrentConditions`, `ForecastDay`, `DayCall`,
 * `ForecastHour`, `EarlierCall`, and the eleven of the track-record tree (#109). There is no
 * longer a type a reader could take for guarded and find is not. What it still cannot say is
 * anything finer than one field: `Reading` and `HeightRange` are decided about as parts of the
 * fields holding them, so a reading whose *unit* alone went unread would pass everything here.
 * That is the next hole, and it is named rather than left to be found.
 *
 * **The "not read" arm carries as much weight as the other.** Fourteen fields are declared
 * unread and every one states why: five on `ForecastHour`, whose Combined Sea and temperatures
 * belong to the panel above the forecast; `Forecast.stale` and `stale_after_hours`, which the
 * page reads once from `CurrentConditions` instead; five of `Calibration`'s eight, which are the
 * provenance of the fit rather than its size; `TierRecord.precision_lower_bound`, whose
 * complement is printed instead because the page would rather be judged on the unkind number;
 * and `DeliveryRecord.maximum_m`, the one figure of three that flatters. Both arms are verified
 * in both directions — rendering a field declared unread fails its test, and ceasing to render
 * one declared read fails its own, each alone.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import type {
  AccuracyBand,
  Calibration,
  CallStatus,
  CurrentConditions,
  DayCall,
  DaySpread,
  DeliveredStepRecord,
  DeliveryRecord,
  EarlierCall,
  Forecast,
  ForecastDay,
  ForecastHour,
  HeightRange,
  IssuedRecord,
  ModelAgreement,
  PanelRecord,
  RangeCalibration,
  RangeCoverage,
  RangeLead,
  Reading,
  RecordedDay,
  TierRecord,
  TrackRecord,
} from './api';
import { App } from './App';
import { ForecastRange } from './Forecast';
import { TrackRecordPage } from './TrackRecord';
import {
  calibration,
  currentConditions,
  forecast,
  trackRecord,
  unmeasurableSpread,
} from './test/handlers';
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
 *
 * **It takes a thunk rather than a day, so that adding a second renderer could not add a second
 * verdict (#107).** `CurrentConditions` is drawn by `panelFor` and everything else by `pageFor`,
 * and the first draft of that block inlined its own two assertions — reintroducing exactly the
 * split above, in the change that was widening the guard. The registries decide what is read;
 * this is the only place that decides what "read" costs.
 */
async function holdToVerdict(
  spec: Decision,
  sent: unknown,
  changed: unknown,
  draw: () => Promise<string>,
  baseline: string,
): Promise<void> {
  expect(moved(sent, changed, spec.note)).toBe(true);

  const after = await draw();

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

/* The four mutations both call registries share. `EarlierCall` is a cut-down `DayCall` — five of
 * its fields are the same five quantities — so the same four `other` functions were written out
 * twice, which is the duplication `feet` and `veer` above already exist to prevent.
 *
 * Named for the operation and not for its consequence, because the consequence differs by site:
 * `noCall` applied to the superseded runs leaves a date *newly raised* to a Watch, and applied to
 * the current call leaves one *withdrawn*. The sentence explaining which is at each call site. */
const noCall = (): CallStatus => 'none';
const furtherOut = (days: number): number => days + 2;
const higher = (r: Reading): Reading => ({ ...r, value: Number((r.value + 1.7).toFixed(2)) });
const wider = (range: HeightRange | null): HeightRange | null =>
  range && { ...range, low: range.low - 0.8, high: range.high + 0.8 };

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

      await holdToVerdict(spec, BIG.hours, changed.hours, () => pageFor(changed), baseline);
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

/**
 * Four superseded runs about one date, which is what `recent_calls` sends at its default
 * bound of five.
 *
 * **Coherent with the call they sit under, which took a correction to get right.** `BIG_CALL`
 * speaks at 4 days out about 2026-02-13, so the run that issued it spoke on the 9th and every
 * run behind it spoke earlier and further out. A series stamped later than the call it precedes
 * is not a fixture the backend can produce, and this file has no business asserting anything
 * about impossible input.
 *
 * **Lead Times repeat, deliberately.** Pipeline Runs are three-hourly (`cycle.py`) while
 * `lead_time_days` is a whole number of days, so consecutive runs about one date routinely share
 * one — which is what makes the stamp, and not the Lead Time, the thing that orders these rows.
 * `Forecast.test.tsx` builds its series the same way, and #99 was caught building the impossible
 * version.
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
  run('2026-02-07T00:00:00Z', 6, 6.2),
  run('2026-02-07T12:00:00Z', 6, 7.1),
  run('2026-02-08T00:00:00Z', 5, 8.0),
  run('2026-02-08T12:00:00Z', 5, 8.3),
];

/**
 * `BIG`'s own call with those runs behind it — the baseline both blocks below start from.
 *
 * **The series was raised to meet the call, rather than the call lowered to meet the series
 * (#104).** This used to override `predicted_significant_wave_height` down to 6.4 m so that the
 * last run's 6.2 m sat just behind it, and that bought the wrong coherence twice over. It left
 * the prediction outside the 7.6–9.7 m `plausible_range` it inherited. And it put a Significant
 * Wave Height of 6.4 m on a day whose peak hour carries 8.1 m of *swell* — `CONTEXT.md` makes
 * the Combined Sea the whole sea and Swell "only the travelled component" of it, so a Combined
 * Sea under its own swell is not a reading the ocean produces, let alone the backend.
 * `handlers.ts` derives the figure as that hour's swell height plus 0.4 m for exactly this
 * reason, and the page renders both at once: 8.1 m on the card, 6.4 m in the panel under it.
 *
 * Moving the runs instead leaves the call precisely as `handlers.ts` derives it, which is the
 * only version of it the backend can emit. The last run still lands 0.2 m below the current one,
 * which is the step a three-hourly cycle takes and what `Shift` is written about.
 */
const CALL_WITH_HISTORY: DayCall = { ...BIG_CALL, previous_runs: RUNS };

const dayWith = (call: DayCall): ForecastDay => ({ ...BIG, call });

describe('EarlierCall', () => {
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
      other: furtherOut,
    },
    status: {
      read: true,
      note: 'the tier badge on each row',
      // A date newly raised to a Watch, rather than one that flickered between tiers.
      other: noCall,
    },
    predicted_significant_wave_height: {
      read: true,
      note: 'the height on each row, and the shape the bar draws from them',
      other: higher,
    },
    plausible_range: {
      read: true,
      note: 'the range beside each height',
      // Nullable on the wire and never null here: a series mixing calls that carry a range
      // with calls that do not is `Forecast.test.tsx`'s case, and it asserts the wording.
      other: wider,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    const what = spec.read ? 'read on every run, not only the last' : 'not read';
    it(`${name} is ${what} — ${spec.note}`, async () => {
      const baseline = await pageFor(dayWith(CALL_WITH_HISTORY));
      // The most recent run is left alone deliberately. `Shift` reads `at(-1)` and always
      // did; holding it still means any difference below comes from the runs behind it,
      // which is precisely the distinction #99 turned on. Mutating the whole list lets the
      // shipped-before-#99 page pass three of these five.
      const changed = RUNS.map((sent, index) =>
        index === RUNS.length - 1 ? sent : replace(sent, name, spec.other),
      );

      await holdToVerdict(
        spec,
        RUNS,
        changed,
        () => pageFor(dayWith({ ...CALL_WITH_HISTORY, previous_runs: changed })),
        baseline,
      );
    });
  }
});

describe('DayCall', () => {
  /**
   * The call the panel is drawn from: a Watch the wave models refused a Go Call on.
   *
   * **Four of the eleven are read only inside a branch, and exactly one of those branches is
   * why this baseline exists.** `height_bar_probability`, `uncertainty_measured` and
   * `go_call_withheld_for_uncertainty` are reached only inside `PlausibleRange`, which renders
   * nothing at all without a `plausible_range` — a gate `handlers.ts` already opens, so those
   * three needed nothing arranged and this block claims no credit for them. `model_agreement` is
   * the one that did: it is reached only where `go_call_withheld` is true, `handlers.ts`
   * withholds nothing, and so on the shipped fixture a mutation of it renders an identical page.
   * This file would then have certified as unread the field that decides what the card says on
   * every withheld call.
   *
   * **`previous_runs` is the opposite case, and fails loudly rather than lying.** It is read
   * unconditionally — `Shift` takes it and `History` takes it — but it renders nothing with no
   * runs behind it, and `handlers.ts` sends none. Mutating an empty list moves nothing, so
   * `moved` fails the test outright instead of certifying anything about it. It needs the runs
   * all the same; it simply could not have gone quiet.
   *
   * **It is still a call the backend could issue, rather than a shape assembled to reach those
   * branches.** A date the forecasters have not settled on is exactly the date a Go Call is
   * withheld on, so the status is a Watch — and the reasons are the ones `handlers.ts` emits for
   * one. A Go Call's "3 of 24 hours match every condition" sitting under a Watch badge would be
   * the fixture lying about which tier produced it, which is the failure the coherence bar at the
   * top of this file exists to keep out of the baseline.
   */
  const WITHHELD: DayCall = {
    ...CALL_WITH_HISTORY,
    status: 'watch',
    reasons: [
      'swell period 17s',
      'wind is offshore and light',
      '24 of 24 forecast hours carry the swell behind this Watch',
    ],
    model_agreement: 'divided',
    go_call_withheld: true,
  };

  /** What the call panel does with each of the eleven fields a call carries.
   *
   * All eleven are read. That is worth stating rather than passing over: the "not read" arm of
   * this file is populated entirely by `ForecastHour`, whose Combined Sea and temperatures
   * belong to the panel above the forecast, and nothing a *call* carries reaches the page
   * unrendered. */
  const fields: Registry<DayCall> = {
    status: {
      read: true,
      note: 'the badge on the card, the verdict sentence under it, and the tier change across runs',
      // Withdrawn rather than raised. A run that stops calling a date is the transition story 21
      // was written about, and the one that used to render identically to a date never called at
      // all. It no longer agrees with the withholding flag beside it, which is what moving one
      // field of a pair always costs.
      other: noCall,
    },
    lead_time_days: {
      read: true,
      note: 'how far ahead the call was issued — in the panel, and on the current row of the series',
      // Further out, and still inside the seven days the archive reaches, so the measured-width
      // flag below it stays true of the baseline it is mutated off.
      other: furtherOut,
    },
    reasons: {
      read: true,
      note: 'the list under the verdict',
      // One reason fewer. The backend emits one per condition it checked, so a shorter list is a
      // response it produces rather than a string edited until it differed.
      other: (reasons) => reasons.slice(1),
    },
    predicted_significant_wave_height: {
      read: true,
      note: 'the figure the panel states, the size of the shift since the run before, and the bar on the current row',
      other: higher,
    },
    go_call_withheld: {
      read: true,
      note: 'the marker on the day card, and the same fact spelled out in its aria-label',
      // Nothing withheld, which drops the marker back to whatever the Model Spread says — here,
      // nothing at all. Null would render the same page and prove less: this asks for the flag
      // to be read as a fact rather than merely for its presence.
      other: () => false,
    },
    model_agreement: {
      read: true,
      note: 'which of the two refusals the card names — "models divided" or "unchecked"',
      // The other way a Go Call is withheld: too few organisations answered for there to be a
      // disagreement at all. `Forecast.tsx` is explicit that an unmeasured hour must never be
      // reported as forecasters disagreeing, and this is the field that decides which is said.
      other: () => 'unmeasured' as ModelAgreement,
    },
    plausible_range: {
      read: true,
      note: 'the range under the call, and the range on the current row of the series',
      other: wider,
    },
    height_bar_probability: {
      read: true,
      note: 'the percentage beside the range, and the scope paragraph that exists only beside it',
      // A share, which the page rounds to whole percent — so `DISPLAYED` is one percentage point
      // here, and this clears it by twenty-seven.
      other: () => 0.55,
    },
    uncertainty_measured: {
      read: true,
      note: 'the alert saying the width out here is extrapolated rather than measured',
      // False specifically, and not null. The alert turns on `=== false`, so a call issued
      // before the flag existed renders exactly as a measured one — mutating to null would
      // certify a rendered field as unread, which is the branch problem this block is about.
      // It stops agreeing with the four-day Lead Time beside it, and that is the usual cost.
      other: () => false,
    },
    go_call_withheld_for_uncertainty: {
      read: true,
      note: 'the sentence separating a forecast too uncertain to book on from forecasters who disagree',
      // Both refusals at once. They are different facts about one call and the backend can
      // report both, which is why they are two fields rather than one.
      other: () => true,
    },
    previous_runs: {
      read: true,
      note: 'the shift since the run before, the tier change across it, and the series under both',
      // One run shorter, which is what a date spoken about four times sends. It moves the run
      // `Shift` compares against as well as the length of the series — and that breadth is the
      // point: this field asks whether the list reaches the page at all, while the registry
      // above asks what is read off each run inside it.
      other: (runs) => runs.slice(0, -1),
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await pageFor(dayWith(WITHHELD));
      const changed = replace(WITHHELD, name, spec.other);

      await holdToVerdict(spec, WITHHELD, changed, () => pageFor(dayWith(changed)), baseline);
    });
  }
});

describe('ForecastDay', () => {
  /**
   * What the range does with each of the eight fields a day carries.
   *
   * All eight are read, and one of them is read *only by a screen reader*:
   * `longest_swell_period` is on no card and in no panel, only inside the card's `aria-label`.
   * It is the day's groundswell signal — the longest period the day reaches, which can fall at a
   * quieter hour — so a version of this file that compared visible text would file the most
   * load-bearing figure on the card as dropped, and be wrong in the direction that gets a field
   * deleted. #25 is the ticket where an `aria-label` losing a figure was itself the whole defect.
   *
   * The baseline is `BIG` exactly as `handlers.ts` builds it, and only one field here is gated
   * at all: `call`, which decides whether the whole panel under the card renders, and which
   * `BIG` carries. `model_spread` looks like a second and is not — `agreementFlag` reaches it
   * only on a call that withholds nothing, but `Agreement` reads it with no such gate, so the
   * field arrives on the page either way and only the card's marker turns on the call above it.
   * That asymmetry is why this block needed no baseline of its own while the one above did.
   */
  const fields: Registry<ForecastDay> = {
    date: {
      read: true,
      note: 'the card label, the panel headings, the hourly caption, and the grouping of the range',
      // A year on: the one shift that lands on a real date whatever the date was, and that
      // cannot collide with the days either side. It leaves the day sitting between two 2026
      // dates with its own hours still stamped 2026 — an incoherence, and an unavoidable one,
      // since the date is what orders the range and what `days.py` groups the hours under. No
      // coherent fixture can move it alone.
      other: (date) => `${Number(date.slice(0, 4)) + 1}${date.slice(4)}`,
    },
    call: {
      read: true,
      note: 'the verdict on the card and the whole panel beneath it',
      // A day no pipeline run has judged, which the API sends as null. Distinct from a call of
      // status `none`, which was judged and dismissed — and the page renders them differently
      // on purpose.
      other: () => null,
    },
    peak_swell_height: {
      read: true,
      note: 'the figure on the card, its aria-label, and how the card ranks against the range',
      other: feet,
    },
    swell_period_at_peak: {
      read: true,
      note: 'the period beside the height on the card, and in its aria-label',
      other: longer,
    },
    swell_direction_at_peak: {
      read: true,
      note: 'the compass point on the card, and in its aria-label',
      other: veer,
    },
    longest_swell_period: {
      read: true,
      note: 'the aria-label and nowhere else — this figure reaches a screen reader alone',
      other: longer,
    },
    model_spread: {
      read: true,
      note: 'the agreement section, and the marker a card carries when less than a full read stood behind it',
      // A date nobody could measure: a stored response, not an absent key, which would read as
      // agreement. All three readings go together because the roster is asked once — so this is
      // one coherent value for one field rather than three fields moved in step.
      other: (spread) =>
        Object.fromEntries(
          Object.keys(spread).map((reading): [string, DaySpread] => [reading, unmeasurableSpread]),
        ),
    },
    hours: {
      read: true,
      note: 'every row of the hourly table',
      // A day clipped short, which is how the last day of a range arrives. It asks only whether
      // the list reaches the table at all; what is read off each hour inside it is the first
      // registry in this file.
      other: (hours) => hours.slice(0, -1),
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await pageFor(BIG);
      const changed = replace(BIG, name, spec.other);

      await holdToVerdict(spec, BIG, changed, () => pageFor(changed), baseline);
    });
  }
});

/**
 * Everything the page draws for one set of current conditions, as markup.
 *
 * `<App />` rather than the panel alone, for the reason `pageFor` renders the whole range: the
 * question is whether a value reaches a reader *anywhere*, and a helper pinned to the readings
 * list would file the two stamps in the footer and the coordinates in the provenance line as
 * dropped.
 *
 * All three fetches are waited on. The current panel is `App`'s own, but the forecast and the
 * track record render inside it and settle on their own schedules — snapshotting before they
 * land would compare a half-built page against a built one, which differs for every field and
 * would call all sixteen read.
 */
async function panelFor(conditions: CurrentConditions): Promise<string> {
  server.use(http.get('*/api/conditions/current', () => HttpResponse.json(conditions)));

  const view = render(<App />);
  await screen.findByTestId('freshness');
  await screen.findByTestId('earliest-call');
  await screen.findByTestId('gold-day-total');

  const html = view.container.innerHTML;
  view.unmount();
  return html;
}

describe('CurrentConditions', () => {
  /**
   * The conditions panel, on a response the backend has marked stale.
   *
   * **`stale_after_hours` is read only inside the staleness banner, and `handlers.ts` is not
   * stale (#107).** So on the shipped fixture a mutation of that field renders a byte-identical
   * page, and this file would certify as unread the figure the banner is built around — the same
   * trap `DayCall.model_agreement` sprang, in the type whose readings a reader is most likely to
   * assume are already guarded. `ForecastHour` is literally an `Omit` of this one.
   *
   * **A stale response is one the backend emits, and the stamps beside the flag do not
   * contradict it.** Staleness is the backend's verdict and arrives as a flag precisely so this
   * layer does not derive it — `api.ts` says so, and `App.tsx` repeats it — so a response can
   * carry `stale: true` with any pair of stamps on it. Nothing on the page compares the two.
   */
  const STALE: CurrentConditions = { ...currentConditions, stale: true };

  /** What the page does with each of the sixteen fields the current reading carries.
   *
   * All sixteen are read, `latitude` and `longitude` included — the provenance line under the
   * footer prints both to two decimals, which is the sentence saying these figures are modelled
   * at a grid point rather than measured at the beach. They looked like the likeliest pair on
   * the wire to be carried and never shown, and they are not. */
  const fields: Registry<CurrentConditions> = {
    observed_at: {
      read: true,
      note: 'the older of the two stamps in the footer — how old the picture itself is',
      // Three hours on, keeping the naive shape the wire uses for this one field. It stops
      // agreeing with the fetch stamp beside it, which is the usual cost of moving one of a
      // pair; nothing on the page compares them.
      other: (at) => shiftHours(at, 3),
    },
    fetched_at: {
      read: true,
      note: 'the second stamp in the footer — when the run that produced this ran',
      // Through `Date`, because this stamp carries an explicit offset where `observed_at` does
      // not. It comes back as `Z` rather than `+00:00`, which is the same instant written the
      // other way and the same shape: an instant that states its zone.
      other: (at) => new Date(new Date(at).getTime() + 3 * 3_600_000).toISOString(),
    },
    stale: {
      read: true,
      note: 'whether the banner above everything else renders at all',
      // Fresh, which takes the banner away. The flag is the backend's verdict and this layer
      // only reads it, so either value is a response it could send.
      other: () => false,
    },
    stale_after_hours: {
      read: true,
      note: 'the number of hours the banner states, which is why the banner has to be reachable',
      // Six hours further, so the page cannot go on saying "six" from a literal. It was written
      // here as one once, which a change of cadence would have made silently untrue.
      other: (hours) => hours + 6,
    },
    latitude: {
      read: true,
      note: 'the north coordinate in the provenance line, to two decimals',
      // A different grid point rather than a different ocean: 0.05° is about five kilometres,
      // which moves the second decimal the line prints without landing the forecast inland.
      other: (lat) => lat + 0.05,
    },
    longitude: {
      read: true,
      note: 'the west coordinate in the provenance line, printed as its own magnitude',
      // Further out to sea. The page renders `Math.abs`, so this moves the printed figure only
      // because it moves away from zero — a mutation toward it would have to clear the same bar.
      other: (lon) => lon - 0.05,
    },
    swell_height: { read: true, note: 'the swell height reading', other: feet },
    swell_period: { read: true, note: 'the swell period reading', other: longer },
    swell_direction: {
      read: true,
      note: 'the swell direction reading, as degrees and a compass point beside them',
      other: veer,
    },
    significant_wave_height: {
      read: true,
      note: 'the combined sea’s height — shown here for now, which is what makes it a column nowhere else',
      other: feet,
    },
    wave_period: { read: true, note: 'the combined sea’s period', other: longer },
    wave_direction: {
      read: true,
      note: 'the combined sea’s direction, as degrees and a compass point',
      other: veer,
    },
    water_temperature: { read: true, note: 'the water temperature reading', other: fahrenheit },
    air_temperature: { read: true, note: 'the air temperature reading', other: fahrenheit },
    wind_speed: { read: true, note: 'the wind speed reading', other: mph },
    wind_direction: {
      read: true,
      note: 'the wind direction reading, as degrees and a compass point',
      other: veer,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await panelFor(STALE);
      const changed = replace(STALE, name, spec.other);

      await holdToVerdict(spec, STALE, changed, () => panelFor(changed), baseline);
    });
  }
});

/**
 * The whole forecast response as the range draws it, with one day open.
 *
 * `pageFor` above swaps the *days* into the shipped response and so can say nothing about the
 * response's own fields. This serves a response entire, which makes `calibrated`,
 * `amplification_model` and the rest the things being moved.
 *
 * A day is opened because two of those fields are reachable only through the panel a click
 * opens, and `BIG` is the day opened — so no mutation below may take it out of the range.
 */
async function rangeFor(response: Forecast): Promise<string> {
  server.use(http.get('*/api/conditions/forecast', () => HttpResponse.json(response)));

  const view = render(<ForecastRange />);
  await userEvent.click(await screen.findByRole('button', { name: new RegExp(BIG.date) }));
  await screen.findByRole('table');

  const html = view.container.innerHTML;
  view.unmount();
  return html;
}

/** A forecast whose calls were decided against fitted thresholds, which `handlers.ts` is not.
 *
 * The uncalibrated banner and the calibrated one are alternatives, and `Calibration` is reachable
 * only through the second — `calibrated && calibration` guards it. On the shipped fixture the
 * whole type sits behind a closed gate, so all eight of its fields would have read as unread. */
const CALIBRATED: Forecast = { ...forecast, calibrated: true, calibration };

describe('Forecast', () => {
  /** What the range does with each of the seven fields the response itself carries.
   *
   * **Five are read and two are not — the first "not read" verdicts this file has recorded
   * outside `ForecastHour`.** `stale` and `stale_after_hours` ride on this response because, as
   * `api.ts` puts it, both endpoints serve the same pipeline run. The page reads neither of them
   * here. The staleness banner is rendered once, above everything, from `CurrentConditions`,
   * which is the right place for it: somebody deciding whether to book should learn the data is
   * old before they read any of it, not once per section.
   *
   * So these two are duplication the wire carries and the page deliberately declines, which is a
   * different thing from the defect this file was built for. `wind_direction` had nowhere else
   * to be read; these have somewhere better. */
  const fields: Registry<Forecast> = {
    fetched_at: {
      read: true,
      note: 'the stamp in the provenance line under the range',
      other: (at) => new Date(new Date(at).getTime() + 3 * 3_600_000).toISOString(),
    },
    stale: {
      read: false,
      note:
        'not read here — the staleness banner is rendered once above everything from ' +
        'CurrentConditions, so this copy of the same run’s verdict reaches nothing',
      other: () => true,
    },
    stale_after_hours: {
      read: false,
      note: 'not read here, for the reason `stale` is not: the banner states the figure it arrived with',
      other: (hours) => hours + 6,
    },
    amplification_model: {
      read: true,
      note: 'which provenance sentence the call panel carries, and whether it carries one at all',
      // The learned fit — the other name `Forecast.tsx` matches explicitly rather than taking as
      // an else-branch, because "carried through unchanged" is a claim about arithmetic nobody
      // has seen and an unrecognised model has no honest sentence.
      other: () => 'learned-amplification',
    },
    calibrated: {
      read: true,
      note: 'which of the two threshold banners renders — thresholds fitted, or a rule of thumb',
      other: () => false,
    },
    calibration: {
      read: true,
      note: 'the Gold Day counts inside the calibrated banner, which renders nothing without it',
      // A forecast whose calls were decided before there was a fit, which is what the shipped
      // fixture sends and what this field’s `| null` is for.
      other: () => null,
    },
    days: {
      read: true,
      note: 'every card in the range, and the count in the heading above them',
      // One day shorter, from the far end. `BIG` sits at index 1 and has to survive, or the
      // harness could not open the panel it is about to compare.
      other: (days) => days.slice(0, -1),
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await rangeFor(CALIBRATED);
      const changed = replace(CALIBRATED, name, spec.other);

      await holdToVerdict(spec, CALIBRATED, changed, () => rangeFor(changed), baseline);
    });
  }
});

describe('Calibration', () => {
  /** What the calibrated banner does with each of the eight fields a fit carries.
   *
   * **Three are read and five are not, and the five are the provenance of the fit.** The banner
   * says how many Gold Days chose the thresholds, how many were held back, and how few there are
   * in total. It says nothing about which seasons were fitted or validated on, what method
   * produced the fit, when it was made, or which script regenerates it.
   *
   * `source` is the one worth arguing about, and #106 is the reason it is written down rather
   * than left implicit: a principle honoured at one call site and declined at another is how a
   * true statement quietly becomes false. `TrackRecord` renders its own `source` precisely "so a
   * reader can go and check it rather than take it on trust" — and this is the script behind the
   * thresholds every call on the page was decided against. Whether it belongs on screen is not
   * something this guard can settle. Recording the decision is the whole purpose of this arm. */
  const fields: Registry<Calibration> = {
    fitted_on: {
      read: false,
      note:
        'not shown — the banner counts Gold Days rather than naming seasons, and a season range ' +
        'says little to a reader who does not already know which winters were big',
      other: () => '2019/20-2020/21',
    },
    validated_on: {
      read: false,
      note: 'not shown, for the reason `fitted_on` is not',
      other: () => '2021/22-2025/26',
    },
    gold_days_fitted: {
      read: true,
      note: 'the count that chose the thresholds',
      other: (days) => days + 3,
    },
    gold_days_validated: {
      read: true,
      note: 'the count held back to check them',
      other: (days) => days + 2,
    },
    gold_days_total: {
      read: true,
      note: 'the total the banner leads with, in order to say how small it is',
      other: (days) => days + 4,
    },
    method: {
      read: false,
      note:
        'not shown — it describes how the fit was made, and the banner is about how little the ' +
        'fit rests on',
      other: () => 'Swell period fitted per tier against a wider Gold Day panel.',
    },
    source: {
      read: false,
      note:
        'not shown, and arguably the one that should be: TrackRecord renders its own source so a ' +
        'reader can check it rather than trust it, and this is the script behind every threshold',
      other: () => 'analysis/calibration/refit.py',
    },
    fitted_at: {
      read: false,
      note:
        'not shown — the range already carries its own fetch stamp, and a second date beside it ' +
        'would invite reading the age of the fit as the age of the forecast',
      other: () => '2026-06-01',
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await rangeFor(CALIBRATED);
      const changed = replace(calibration, name, spec.other);

      await holdToVerdict(
        spec,
        calibration,
        changed,
        () => rangeFor({ ...CALIBRATED, calibration: changed }),
        baseline,
      );
    });
  }
});

/**
 * A Model Spread measured against less than the full roster.
 *
 * `providers_expected` is read only inside the alert that `degraded` gates, and `handlers.ts`
 * sends every organisation for this reading — so on the shipped fixture that field would read as
 * unread. The same gate one more time, in the third type to have one.
 *
 * Two of three organisations, with `lowest` and `highest` bracketing `spread` exactly around
 * `BIG`'s middle hour, because that is how the backend derives them: one real hour's real
 * measurement rather than three numbers assembled separately.
 */
const DEGRADED_SPREAD: DaySpread = {
  unit: 'm',
  spread: 0.3,
  lowest: 7.38,
  highest: 7.68,
  providers: ['DWD', 'NCEP'],
  degraded: true,
  providers_expected: 3,
  bearing: false,
  hours_measured: 24,
  hours_total: 24,
};

describe('DaySpread', () => {
  /** What the agreement section does with each of the ten fields a spread carries.
   *
   * All ten are read, which is the answer that makes `ForecastDay.model_spread` worth having as
   * its own entry rather than trusted: that registry decides the *map* reaches the page and can
   * say nothing about any single spread inside it. This is the half of the pair that can. */
  const spreadWith = (spread: DaySpread): ForecastDay => ({
    ...BIG,
    model_spread: { ...BIG.model_spread, swell_height: spread },
  });

  const fields: Registry<DaySpread> = {
    unit: {
      read: true,
      note: 'the unit beside the gap, and beside both ends of the arc under it',
      // The unit alone, with the value left where it was. That is incoherent as a measurement
      // and it is precisely the question being asked: whether the page reads the unit it was
      // sent or prints one it assumed.
      other: () => 'ft',
    },
    spread: {
      read: true,
      note: 'how far apart the forecasters are at this day’s middle hour',
      other: (gap) => (gap === null ? null : Number((gap + 0.6).toFixed(2))),
    },
    lowest: {
      read: true,
      note: 'the low end of the arc the gap was measured across',
      other: (low) => (low === null ? null : Number((low - 0.4).toFixed(2))),
    },
    highest: {
      read: true,
      note: 'the high end of that arc',
      other: (high) => (high === null ? null : Number((high + 0.4).toFixed(2))),
    },
    providers: {
      read: true,
      note: 'the organisations named under the paragraph, and how many the sentence counts',
      // Different names, same count. Holding the length still is what makes this a question
      // about the names rather than about `degraded`, which is its own field below.
      other: () => ['DWD', 'MeteoFrance'],
    },
    degraded: {
      read: true,
      note: 'the alert under the paragraph, and the marker the day card carries',
      // Not degraded, which takes the alert away. It stops agreeing with the two names beside
      // it — the backend derives one from the other — and that is the usual cost of moving one
      // field of a pair.
      other: () => false,
    },
    providers_expected: {
      read: true,
      note: 'the roster size the alert counts against, sent rather than known here',
      // A roster that grew, which is exactly why this arrives over the wire: "two of three"
      // must not go on saying three after a fourth organisation joins.
      other: (expected) => expected + 2,
    },
    bearing: {
      read: true,
      note: 'whether the two ends are read as a compass arc or as an interval on a line',
      // True, which turns the pair into an arc: across north the second number is the smaller
      // one, and reading it as a minimum and a maximum would name the wrong 350 degrees.
      other: () => true,
    },
    hours_measured: {
      read: true,
      note: 'how many of the day’s hours a spread could be measured for',
      other: (hours) => hours - 6,
    },
    hours_total: {
      read: true,
      note: 'how many hours the day has, which is what that count is out of',
      // A day clipped short, as the end of a range arrives.
      other: (hours) => hours - 1,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await pageFor(spreadWith(DEGRADED_SPREAD));
      const changed = replace(DEGRADED_SPREAD, name, spec.other);

      await holdToVerdict(
        spec,
        DEGRADED_SPREAD,
        changed,
        () => pageFor(spreadWith(changed)),
        baseline,
      );
    });
  }
});

/**
 * The track record as its own page draws it.
 *
 * `<TrackRecordPage />` alone rather than through `App`, and that is a claim rather than a
 * shortcut: `fetchTrackRecord` has exactly one caller, and the section fetches independently so
 * that a failure here costs the record and not the forecast. So this subtree is everything that
 * could read one of these values, and rendering the app around it would only add two more
 * requests to wait on.
 *
 * The provenance line is the last thing on the page, so waiting for it waits for all of it.
 */
async function recordFor(record: TrackRecord): Promise<string> {
  server.use(http.get('*/api/track-record', () => HttpResponse.json(record)));

  const view = render(<TrackRecordPage />);
  await screen.findByTestId('record-provenance');

  const html = view.container.innerHTML;
  view.unmount();
  return html;
}

/** An installation that has issued calls, which `handlers.ts` has not.
 *
 * `IssuedRecord` has three branches — the store could not be read, nothing has been issued yet,
 * and a real history — and the shipped fixture takes the middle one, where four of its five
 * fields are never reached. All five would have read as unread. A fresh installation is the
 * honest default for that fixture and the wrong baseline for this question.
 *
 * 148 calls over 37 dates is a three-hourly cadence speaking about a fortnight of dates at a
 * time, and nine of them Go Calls is the proportion the record's own precision implies. */
const ISSUED: IssuedRecord = {
  calls_issued: 148,
  dates_covered: 37,
  go_calls_issued: 9,
  first_issued_at: '2026-02-01T00:00:00Z',
  last_issued_at: '2026-08-14T12:00:00Z',
};

const RECORD: TrackRecord = { ...trackRecord, issued: ISSUED };

/** The held-out panel's Go Call tier, rebuilt into a whole record.
 *
 * That tier and not another, because it is the one the page reads three separate ways: the row
 * in the panel, the waste statement under it, and the delivery section under that. A tier read
 * once would answer a narrower question than the registry claims to. */
const withGoCall = (tier: TierRecord): TrackRecord => ({
  ...RECORD,
  held_out: { ...RECORD.held_out, go_call: tier },
});

const GO_CALL = RECORD.held_out.go_call;
const DELIVERED = GO_CALL.delivered!;
const STEP = DELIVERED.above[0]!;
const RANGE = RECORD.range_calibration;
const LEAD = RANGE.leads[0]!;

describe('TrackRecord', () => {
  /** What the page does with each of the twelve fields the record itself carries. All twelve
   * are read: this type is the page's spine, and every one of its fields is a section. */
  const fields: Registry<TrackRecord> = {
    published_at: {
      read: true,
      note: 'the date in the provenance line at the foot of the record',
      other: () => '2026-08-14',
    },
    source: {
      read: true,
      note: 'the script named in the provenance line, so a reader can regenerate the figures',
      other: () => 'analysis/track_record/republish.py',
    },
    held_out: {
      read: true,
      note: 'the panel to judge the system by, the basis caveat, and the waste statement',
      other: (panel) => ({ ...panel, gold_days: panel.gold_days + 7 }),
    },
    full_record: {
      read: true,
      note: 'the second panel, and the span and season count the page opens with',
      other: (panel) => ({ ...panel, big_wave_seasons: panel.big_wave_seasons + 4 }),
    },
    scored: {
      read: true,
      note: 'the accuracy table for both models reading the reconstruction directly',
      // One band shorter. `api.ts` refuses a record whose bands lack either model, so a band
      // may be removed but never emptied.
      other: (bands) => bands.slice(0, -1),
    },
    served: {
      read: true,
      note: 'the accuracy table along the path the running system actually takes',
      other: (bands) => bands.slice(0, -1),
    },
    range_calibration: {
      read: true,
      note: 'the whole section asking whether the range printed on every forecast means what it says',
      other: (calibration) => ({ ...calibration, claimed: 0.75 }),
    },
    gold_days_fitted: {
      read: true,
      note: 'how many confirmed days chose the thresholds',
      other: (days) => days + 5,
    },
    gold_days_validated: {
      read: true,
      note: 'how many were held back, said twice — in the lead and in the limitations',
      other: (days) => days + 5,
    },
    gold_days_total: {
      read: true,
      note: 'the total everything on the page rests on, said twice for the same reason',
      other: (days) => days + 7,
    },
    days: {
      read: true,
      note: 'every row of the day-by-day table, and the count in its caption',
      other: (days) => days.slice(0, -1),
    },
    issued: {
      read: true,
      note: 'what this installation has issued for real, as against what the reports reconstruct',
      // The store could not be opened, which is "we do not know" and renders differently from
      // an installation that has issued nothing — reporting the second for the first would
      // invent the more flattering of the two.
      other: () => null,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(RECORD, name, spec.other);

      await holdToVerdict(spec, RECORD, changed, () => recordFor(changed), baseline);
    });
  }
});

describe('PanelRecord', () => {
  /** What a panel does with each of its six fields, measured on the held-out one.
   *
   * The held-out panel and not the full record, because `basis` is read from this one alone —
   * the caveat above both panels names the held-out basis. The same field on `full_record`
   * reaches nothing, which is a fact about that one instance rather than about the type, and is
   * exactly the sort of thing a registry keyed by type cannot say. */
  const panelIn = (panel: PanelRecord): TrackRecord => ({ ...RECORD, held_out: panel });
  const PANEL = RECORD.held_out;

  const fields: Registry<PanelRecord> = {
    span: { read: true, note: 'the span in the panel’s caption', other: () => '2019/20-2025/26' },
    basis: {
      read: true,
      note: 'what produced the calls, stated once above both panels before any figure',
      other: () => 'Reanalysis',
    },
    gold_days: {
      read: true,
      note: 'how many confirmed giant days the span contains',
      other: (days) => days + 6,
    },
    big_wave_seasons: {
      read: true,
      note: 'how many Big-Wave Seasons those days fall across',
      other: (seasons) => seasons + 3,
    },
    watch_or_better: {
      read: true,
      note: 'the Watch row of the panel',
      other: (tier) => ({ ...tier, days_flagged: tier.days_flagged + 40 }),
    },
    go_call: {
      read: true,
      note: 'the Go Call row, the waste statement and the delivery section',
      other: (tier) => ({ ...tier, gold_days_called: tier.gold_days_called + 2 }),
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(PANEL, name, spec.other);

      await holdToVerdict(spec, PANEL, changed, () => recordFor(panelIn(changed)), baseline);
    });
  }
});

describe('TierRecord', () => {
  /** What the page does with each of the nine fields a tier carries.
   *
   * **Eight are read and `precision_lower_bound` is not, which is a decision rather than an
   * omission.** The page renders its complement — the share of flagged days that would have been
   * wasted — and says why in the paragraph itself: the figure "is quoted the unkind way round
   * because this number is asking you to spend money". Printing the precision beside the waste
   * would put the flattering half of one fact next to the unflattering half of the same fact,
   * and a reader would take the kinder one. So the wire carries both and the page picks the
   * direction it is willing to be judged on. */
  const fields: Registry<TierRecord> = {
    gold_days_called: {
      read: true,
      note: 'how many confirmed giant days the tier caught, in the row and the waste statement',
      other: (days) => days + 3,
    },
    gold_days_in_panel: {
      read: true,
      note: 'how many there were to catch',
      other: (days) => days + 4,
    },
    days_flagged: {
      read: true,
      note: 'how many days it flagged, said in the row, the waste statement and the delivery',
      other: (days) => days + 25,
    },
    recall: {
      read: true,
      note: 'that catch rate as a whole percentage beside the counts',
      // A whole percentage point is what `percent` can show, and this clears it many times over.
      other: () => 0.5,
    },
    precision_lower_bound: {
      read: false,
      note:
        'not shown. The page renders its complement — the share that would have been wasted — ' +
        'and says it is quoted the unkind way round because it is asking a reader to spend money',
      other: () => 0.5,
    },
    wasted_upper_bound: {
      read: true,
      note: 'the share of flagged days that would have been wasted, at worst',
      other: () => 0.5,
    },
    days_wasted_upper_bound: {
      read: true,
      note: 'that share as a count, in the row and again in the waste statement',
      other: (days) => days + 11,
    },
    flags_per_big_wave_season: {
      read: true,
      note: 'how often the tier fires in a season, to one decimal',
      other: (flags) => flags + 5,
    },
    delivered: {
      read: true,
      note: 'the lowest sea in the row, and the whole delivery section under the waste statement',
      // The Watch tier's case: a record that publishes no delivery for this tier renders none,
      // rather than an empty section that would read as a page that broke.
      other: () => null,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(GO_CALL, name, spec.other);

      await holdToVerdict(spec, GO_CALL, changed, () => recordFor(withGoCall(changed)), baseline);
    });
  }
});

describe('DeliveryRecord', () => {
  /** What the delivery section does with each of its four fields.
   *
   * **Three are read and `maximum_m` is not.** The section leads with the *minimum* deliberately
   * — "no Go Call landed on a day the sea peaked below 2.82m" is the strongest true sentence
   * available here and a reader can check it — and gives the median beside it. The maximum is the
   * one figure of the three that flatters: the biggest day a tier ever caught says nothing about
   * the days it usually catches, and is the number a reader would remember. */
  const deliveredIn = (delivered: DeliveryRecord) => withGoCall({ ...GO_CALL, delivered });

  const fields: Registry<DeliveryRecord> = {
    minimum_m: {
      read: true,
      note: 'the lowest sea any flagged day reached — the headline of the section and of the row',
      other: (m) => m - 1.2,
    },
    median_m: {
      read: true,
      note: 'the middle of them, beside the minimum in both places',
      other: (m) => m + 1.3,
    },
    maximum_m: {
      read: false,
      note:
        'not shown. The section leads with the minimum because it is the checkable claim; the ' +
        'largest day a tier ever caught is the figure that flatters and the one a reader keeps',
      other: (m) => m + 2.6,
    },
    above: {
      read: true,
      note: 'every rung of the ladder under the statement',
      other: (steps) => steps.slice(0, -1),
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(DELIVERED, name, spec.other);

      await holdToVerdict(
        spec,
        DELIVERED,
        changed,
        () => recordFor(deliveredIn(changed)),
        baseline,
      );
    });
  }
});

describe('DeliveredStepRecord', () => {
  /** What one rung of the ladder does with each of its four fields. All four are read. */
  const stepIn = (step: DeliveredStepRecord) =>
    withGoCall({
      ...GO_CALL,
      delivered: { ...DELIVERED, above: [step, ...DELIVERED.above.slice(1)] },
    });

  const fields: Registry<DeliveredStepRecord> = {
    metres: {
      read: true,
      note: 'the height this rung counts days above',
      other: (m) => m + 0.5,
    },
    days: {
      read: true,
      note: 'how many flagged days cleared it',
      other: (days) => days - 12,
    },
    of_days: {
      read: true,
      note: 'how many there were, which is what that count is out of',
      other: (days) => days + 9,
    },
    share: {
      read: true,
      note: 'the same fraction as a whole percentage beside it',
      // Already divided by the backend, and this layer does no arithmetic on it — so the
      // mutation moves the share alone and leaves the two counts saying something else.
      other: () => 0.5,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(STEP, name, spec.other);

      await holdToVerdict(spec, STEP, changed, () => recordFor(stepIn(changed)), baseline);
    });
  }
});

describe('AccuracyBand', () => {
  /** What an accuracy table does with each of the six fields a band carries. All six are read,
   * and both error columns are structurally required — ADR 0006 forbids an accuracy figure
   * without the Heuristic Baseline beside it, and `api.ts` throws rather than render one. */
  const BAND = RECORD.scored[0]!;
  const bandIn = (band: AccuracyBand): TrackRecord => ({
    ...RECORD,
    scored: [band, ...RECORD.scored.slice(1)],
  });

  const fields: Registry<AccuracyBand> = {
    name: {
      read: true,
      note: 'the row heading naming the subset of hours',
      other: () => 'every hour',
    },
    hours: {
      read: true,
      note: 'how many hours the row was measured over',
      other: (hours) => hours + 1574,
    },
    baseline_mae_m: {
      read: true,
      note: 'the rule of thumb’s average error, which every figure here must appear beside',
      other: (m) => m + 0.5,
    },
    learned_mae_m: {
      read: true,
      note: 'the learned model’s average error',
      other: (m) => m + 0.5,
    },
    gain_m: {
      read: true,
      note: 'the signed difference between them, and whether the cell reads as better or worse',
      // Across zero, because the sign is the whole point of the column and is one character.
      other: (m) => m + 0.5,
    },
    caveat: {
      read: true,
      note: 'the note under the table, rendered in full rather than as a marker to chase',
      // This row carries none, and gaining one is the direction that matters: a caveat the
      // backend adds must reach the page, or the strongest-looking figure goes unqualified.
      other: () => 'Measured on a single season.',
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(BAND, name, spec.other);

      await holdToVerdict(spec, BAND, changed, () => recordFor(bandIn(changed)), baseline);
    });
  }
});

describe('RangeCalibration', () => {
  /** What the range section does with each of its five fields. All five are read, and two of
   * them are whole sentences the backend writes rather than figures. */
  const rangeIn = (calibration: RangeCalibration): TrackRecord => ({
    ...RECORD,
    range_calibration: calibration,
  });

  const fields: Registry<RangeCalibration> = {
    claimed: {
      read: true,
      note: 'the share the range says it holds, and what every row is judged against',
      other: () => 0.75,
    },
    big_swell_from_m: {
      read: true,
      note: 'the sea the kinder subset was drawn at, stated in its caption from the record',
      other: (m) => m + 1.5,
    },
    understates_because: {
      read: true,
      note: 'why the figures are a floor, under the tables in full',
      other: () => 'The running range carries a term these draws did not.',
    },
    rests_on: {
      read: true,
      note: 'what the whole table rests on, beside it',
      other: () => 'It rests on a single confirmed giant day.',
    },
    leads: {
      read: true,
      note: 'every row of both tables, and the two lead times the statement above them names',
      other: (leads) => leads.slice(0, -1),
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(RANGE, name, spec.other);

      await holdToVerdict(spec, RANGE, changed, () => recordFor(rangeIn(changed)), baseline);
    });
  }
});

describe('RangeLead', () => {
  /** What one lead time contributes, across its three fields. All three are read, and both
   * subsets are required by the type for the reason `PanelRecord`'s two tiers are: the
   * big-swell rows read kinder than the whole, so no shape may carry one alone. */
  const leadIn = (lead: RangeLead) => ({
    ...RECORD,
    range_calibration: { ...RANGE, leads: [lead, ...RANGE.leads.slice(1)] },
  });

  const fields: Registry<RangeLead> = {
    lead_days: {
      read: true,
      note: 'the row heading, and the lead time the statement above the tables names',
      other: (days) => days + 2,
    },
    all_hours: {
      read: true,
      note: 'this row of the every-hour table, and the coverage the verdict is derived from',
      other: (coverage) => ({ ...coverage, covered: 0.5 }),
    },
    big_swell: {
      read: true,
      note: 'this row of the bigger-seas table',
      other: (coverage) => ({ ...coverage, covered: 0.5 }),
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(LEAD, name, spec.other);

      await holdToVerdict(spec, LEAD, changed, () => recordFor(leadIn(changed)), baseline);
    });
  }
});

describe('RangeCoverage', () => {
  /** What one measured subset contributes, across its five fields.
   *
   * All five are read, and `widening_factor` is the one that needs saying: it is never printed.
   * It reaches a reader only through the clause deciding whether the miss *grows* with lead time
   * — a claim the widths cannot support on their own, because widths grow with lead time whether
   * or not the excess does. So a field rendered nowhere is still read, which is the distinction
   * this whole file turns on. */
  const coverageIn = (coverage: RangeCoverage) => ({
    ...RECORD,
    range_calibration: {
      ...RANGE,
      leads: [{ ...LEAD, all_hours: coverage }, ...RANGE.leads.slice(1)],
    },
  });
  const COVERAGE = LEAD.all_hours;

  const fields: Registry<RangeCoverage> = {
    hours: {
      read: true,
      note: 'the hours in the row, and the figure the statement above the tables leads with',
      other: (hours) => hours + 207,
    },
    covered: {
      read: true,
      note: 'how often the range held, and which way the verdict above the tables falls',
      other: () => 0.5,
    },
    median_width_m: {
      read: true,
      note: 'the width the range prints at this lead time',
      other: (m) => m + 0.6,
    },
    justified_width_m: {
      read: true,
      note: 'the width the outcomes would have asked for',
      other: (m) => m + 0.6,
    },
    widening_factor: {
      read: true,
      note:
        'never printed, and still read: it is the only thing that can say whether the miss grows ' +
        'with lead time, which the widths cannot because they grow either way',
      // Close enough to the longest lead's factor that the growth falls under the tenth of a
      // half-width the page requires before it will say so.
      other: () => 0.55,
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(COVERAGE, name, spec.other);

      await holdToVerdict(spec, COVERAGE, changed, () => recordFor(coverageIn(changed)), baseline);
    });
  }
});

describe('RecordedDay', () => {
  /** What the day-by-day table does with each of the six fields a row carries. All six are
   * read. The row chosen is a confirmed giant day, because `gold_tier` renders only on one. */
  const DAY = RECORD.days[0]!;
  const dayIn = (day: RecordedDay): TrackRecord => ({
    ...RECORD,
    days: [day, ...RECORD.days.slice(1)],
  });

  const fields: Registry<RecordedDay> = {
    date: { read: true, note: 'the row heading', other: () => '2012-01-28' },
    season: { read: true, note: 'the Big-Wave Season column', other: () => '2012/13' },
    call: {
      read: true,
      note: 'what the system called that day',
      other: () => 'go' as CallStatus,
    },
    peak_significant_wave_height_m: {
      read: true,
      note: 'the height column, which the caveat above says is an input and not an outcome',
      other: (m) => m + 1.4,
    },
    gold_day: {
      read: true,
      note: 'the confirmed column, and whether the row is marked as one',
      other: () => false,
    },
    gold_tier: {
      read: true,
      note: 'how it was confirmed, named in brackets beside the yes',
      other: () => 'documented',
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(DAY, name, spec.other);

      await holdToVerdict(spec, DAY, changed, () => recordFor(dayIn(changed)), baseline);
    });
  }
});

describe('IssuedRecord', () => {
  /** What the issued section does with each of its five fields. All five are read — on a
   * baseline that has issued something, which `handlers.ts` has not. */
  const issuedIn = (issued: IssuedRecord): TrackRecord => ({ ...RECORD, issued });

  const fields: Registry<IssuedRecord> = {
    calls_issued: {
      read: true,
      note: 'how many calls this installation has made, and which of the three branches renders',
      other: (calls) => calls + 60,
    },
    dates_covered: {
      read: true,
      note: 'how many dates those calls were about',
      other: (dates) => dates + 9,
    },
    go_calls_issued: {
      read: true,
      note: 'how many of them were Go Calls',
      other: (calls) => calls + 4,
    },
    first_issued_at: {
      read: true,
      note: 'when the first of them was issued',
      other: () => '2026-01-05T00:00:00Z',
    },
    last_issued_at: {
      read: true,
      note: 'when the most recent was',
      other: () => '2026-08-15T09:00:00Z',
    },
  };

  for (const [name, spec] of decisions(fields)) {
    it(`${name} is ${spec.read ? 'read' : 'not read'} — ${spec.note}`, async () => {
      const baseline = await recordFor(RECORD);
      const changed = replace(ISSUED, name, spec.other);

      await holdToVerdict(spec, ISSUED, changed, () => recordFor(issuedIn(changed)), baseline);
    });
  }
});
