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
 * **What this does not cover, so nothing reads it as covering more.** Five of the wire's types:
 * `CurrentConditions` (#107), `ForecastDay`, `DayCall`, `ForecastHour` and `EarlierCall` (#104).
 * That is not everything the site renders, and reading it as such is the over-claim this
 * paragraph exists to stop: `Forecast`'s own fields are on the page, and so are `Calibration`'s
 * three Gold Day counts inside the threshold caveat, and neither has a registry. Nor has the
 * track-record tree, which is the largest uncovered surface left and has a page of its own.
 * `DaySpread` is the half-covered one and so the easiest to over-read:
 * `ForecastDay.model_spread` is decided about as a single field, which proves the map reaches
 * the page and proves nothing whatever about any one of a `DaySpread`'s ten. Nor is this finer
 * than one field anywhere: a field whose *unit* alone went unread would still pass.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import type {
  CallStatus,
  CurrentConditions,
  DayCall,
  DaySpread,
  EarlierCall,
  ForecastDay,
  ForecastHour,
  HeightRange,
  ModelAgreement,
  Reading,
} from './api';
import { App } from './App';
import { ForecastRange } from './Forecast';
import { currentConditions, forecast, unmeasurableSpread } from './test/handlers';
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
