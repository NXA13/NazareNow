/**
 * Default API responses for the frontend suite.
 *
 * Tests import these fixtures and assert against them, so an assertion cannot
 * accidentally match something the component renders statically — that mistake made
 * an earlier loaded-state test pass against a component that fetched nothing, and made
 * a freshness test pass against a broken date formatter.
 *
 * The values describe a genuinely large day so that formatting is exercised on
 * realistic numbers rather than zeros.
 */

import { http, HttpResponse } from 'msw';

import type {
  Calibration,
  CallStatus,
  CurrentConditions,
  DaySpread,
  Forecast,
  TrackRecord,
} from '../api';

export const currentConditions: CurrentConditions = {
  observed_at: '2026-02-13T09:00',
  fetched_at: '2026-02-13T09:04:11.221000+00:00',
  stale: false,
  stale_after_hours: 6,
  latitude: 39.541664,
  longitude: -9.208328,
  swell_height: { value: 8.1, unit: 'm' },
  swell_period: { value: 17.0, unit: 's' },
  swell_direction: { value: 298, unit: '°' },
  significant_wave_height: { value: 8.4, unit: 'm' },
  wave_period: { value: 16.2, unit: 's' },
  wave_direction: { value: 295, unit: '°' },
  water_temperature: { value: 15.2, unit: '°C' },
  air_temperature: { value: 13.4, unit: '°C' },
  wind_speed: { value: 11.0, unit: 'km/h' },
  wind_direction: { value: 115, unit: '°' },
};

/**
 * Every hour differs from every other, in every column the table renders.
 *
 * A fixture of 24 identical hours cannot tell a table that renders each hour from one
 * that renders hour zero 24 times — freezing the swell, period, direction and wind
 * cells all passed. That is the fifth degenerate fixture on this branch, and the first
 * on this side of the seam.
 */
/**
 * A day's hours, peaking mid-afternoon and easing — a shape a real swell actually makes.
 *
 * Every column varies, because 24 identical hours could not tell a table rendering each
 * hour from one rendering hour zero 24 times. But it varies *plausibly*: an earlier
 * version climbed 2.5m monotonically and swept 345 degrees of compass in a day, which is
 * not a response the backend could ever produce. A fixture that is impossible is its own
 * trap — it can hide a bug that only shows on data of a realistic shape.
 *
 * Direction still moves enough to cross compass sectors, since at one degree an hour a
 * frozen direction column rendered identically to a correct one.
 */
function hoursFor(date: string, peak: number, longestPeriod: number, direction: number) {
  const shape = (hour: number) => 1 - Math.abs(hour - 15) / 15; // 0 at midnight, 1 at 15:00
  return Array.from({ length: 24 }, (_, hour) => {
    const swell = peak - (1 - shape(hour)) * (peak * 0.35);
    const period = longestPeriod - (1 - shape(hour)) * 4;
    return {
      at: `${date}T${String(hour).padStart(2, '0')}:00`,
      swell_height: { value: Number(swell.toFixed(2)), unit: 'm' },
      swell_period: { value: Number(period.toFixed(2)), unit: 's' },
      swell_direction: { value: (direction + hour * 5) % 360, unit: '°' },
      significant_wave_height: { value: Number((swell + 0.4).toFixed(2)), unit: 'm' },
      wave_period: { value: Number((period - 2.1).toFixed(2)), unit: 's' },
      wave_direction: { value: (direction + 35 + hour * 5) % 360, unit: '°' },
      water_temperature: { value: Number((15.2 + hour * 0.01).toFixed(2)), unit: '°C' },
      air_temperature: { value: Number((13.4 + hour * 0.02).toFixed(2)), unit: '°C' },
      wind_speed: { value: Number((11 + hour * 0.3).toFixed(2)), unit: 'km/h' },
      wind_direction: { value: (115 + hour * 4) % 360, unit: '°' },
    };
  });
}

/** Every organisation on the backend's roster, in the order the API sorts them. */
export const ALL_PROVIDERS = ['DWD', 'MeteoFrance', 'NCEP'];

/** The Model Spread the backend sends for a date, built around the day's middle hour.
 *
 * `lowest` and `highest` bracket `spread` exactly, because on the backend they are one real
 * hour's real measurement rather than three numbers assembled separately — a fixture whose
 * ends did not bracket its own gap could not catch a component that rendered them
 * inconsistently.
 */
function spreadFor(
  middle: number,
  gap: number,
  unit: string,
  providers = ALL_PROVIDERS,
  bearing = false,
): DaySpread {
  return {
    unit,
    spread: gap,
    lowest: Number((middle - gap / 2).toFixed(2)),
    highest: Number((middle + gap / 2).toFixed(2)),
    providers,
    degraded: providers.length < ALL_PROVIDERS.length,
    providers_expected: ALL_PROVIDERS.length,
    // Named per reading, as the backend names it, rather than derived from `unit` — a fixture
    // that sniffed the degree sign could not catch a component doing the same thing.
    bearing,
    hours_measured: 24,
    hours_total: 24,
  };
}

/** A date nobody could measure: recorded, with nothing in it. Distinct from an absent key,
 * which would read as agreement. */
export const unmeasurableSpread: DaySpread = {
  unit: 'm',
  spread: null,
  lowest: null,
  highest: null,
  providers: [],
  degraded: true,
  providers_expected: ALL_PROVIDERS.length,
  bearing: false,
  hours_measured: 0,
  hours_total: 24,
};

/** A day whose summary is derived from its own hours, so the two cannot contradict.
 *
 * `call` of null is a day the backend holds no call for, which the API returns as
 * `call: null` — distinct from a call whose status is `none`. That one was judged and
 * found not worth travelling for; this one was never judged.
 */
export function dayFrom(
  date: string,
  peak: number,
  longestPeriod: number,
  direction: number,
  call: CallStatus | null = 'none',
  leadTime = 0,
  modelSpread?: Record<string, DaySpread>,
) {
  const hours = hoursFor(date, peak, longestPeriod, direction);
  // The hour the backend's median-hour rule would land on for a 24-hour day. Named rather
  // than indexed inline so the fixture and the comment explaining it cannot drift.
  const middleHour = hours[12]!;
  const peakHour = hours.reduce((a, b) => (b.swell_height.value > a.swell_height.value ? b : a));
  const longestHour = hours.reduce((a, b) => (b.swell_period.value > a.swell_period.value ? b : a));
  return {
    date,
    call:
      call === null
        ? null
        : {
            status: call,
            lead_time_days: leadTime,
            reasons: [
              `swell period ${peakHour.swell_period.value}s`,
              'wind is offshore and light',
              // Tier-accurate, as the backend emits it: a Watch is judged on the swell
              // alone, so counting every condition would print "0 of 24" beside a Watch.
              call === 'watch'
                ? '24 of 24 forecast hours carry the swell behind this Watch'
                : '3 of 24 forecast hours match every condition',
            ],
            // Its own object with its own value. Sharing peak_swell_height's object made
            // rendering the wrong one undetectable, and they are different quantities:
            // CONTEXT.md lists swell height under significant wave height's avoided synonyms.
            predicted_significant_wave_height: {
              value: Number((peakHour.swell_height.value + 0.4).toFixed(2)),
              unit: 'm',
            },
            // Agreed and not withheld, so a fixture day is an ordinary day. The cases where
            // the models refused a Go Call are built by spreading over this in the test that
            // is about them, which keeps the unusual shape beside the assertion it explains.
            model_agreement: 'agreed' as const,
            go_call_withheld: false,
            // A range around the predicted height rather than a pair of round numbers, so a
            // component rendering the wrong end, or rendering the prediction where the range
            // belongs, is visible. Asymmetric for the same reason.
            plausible_range: {
              low: Number((peakHour.swell_height.value - 0.5).toFixed(2)),
              high: Number((peakHour.swell_height.value + 1.6).toFixed(2)),
              unit: 'm',
            },
            height_bar_probability: 0.82,
            // Measured by default: the fixture's lead times sit inside the archive, and the
            // beyond-the-archive case is built by spreading over this in the test about it.
            uncertainty_measured: true,
            go_call_withheld_for_uncertainty: false,
            previous_runs: [],
          },
    peak_swell_height: peakHour.swell_height,
    swell_period_at_peak: peakHour.swell_period,
    swell_direction_at_peak: peakHour.swell_direction,
    longest_swell_period: longestHour.swell_period,
    // Built from the day's middle hour, not its peak, because that is what the backend
    // derives it from — the median hour's spread. A fixture centred on the peak would let a
    // component claim the two describe the same hour and go unnoticed.
    model_spread: modelSpread ?? {
      swell_height: spreadFor(middleHour.swell_height.value, 0.3, 'm'),
      swell_period: spreadFor(middleHour.swell_period.value, 1.2, 's'),
      swell_direction: spreadFor(middleHour.swell_direction.value, 14, '°', ALL_PROVIDERS, true),
    },
    hours,
  };
}

/** A quiet day, a huge day, and an easing day — so tests can prove a small day is shown
 * rather than hidden, and that height, period and direction stay separate. */
export const forecast: Forecast = {
  fetched_at: '2026-02-11T09:04:11.221000+00:00',
  stale: false,
  stale_after_hours: 6,
  amplification_model: 'heuristic-baseline',
  calibrated: false,
  calibration: null,
  days: [
    dayFrom('2026-02-12', 1.4, 8, 250, 'confirmed', 1),
    // Base chosen so the peak hour (15:00, +75 degrees) lands on 298 = WNW, which the
    // tests assert as a literal rather than recomputing it with compassPoint.
    dayFrom('2026-02-13', 8.1, 17, 223, 'go', 4),
    dayFrom('2026-02-14', 5.7, 12, 280, 'watch', 9),
  ],
};

/** The provenance a calibrated forecast carries (#12).
 *
 * The counts are the real ones. A test asserting the interface states how few Gold Days are
 * behind the thresholds should fail if that number silently changes, and inventing a
 * rounder figure here would hide exactly the thing the caveat exists to disclose. */
export const calibration: Calibration = {
  fitted_on: '2021/22-2022/23',
  validated_on: '2023/24-2025/26',
  gold_days_fitted: 6,
  gold_days_validated: 3,
  gold_days_total: 9,
  method: 'Swell period fitted per tier against Gold Days on the real Swell partition.',
  source: 'analysis/calibration/calibrate.py',
  fitted_at: '2026-08-02',
};

/**
 * The published track record (#16).
 *
 * Every figure is the real one, and that is deliberate. This page exists to state the
 * system's limitations plainly, so a fixture with rounder, kinder numbers would let a test
 * assert that the caveats are shown while the component quietly renders a different, more
 * flattering system than the one that ships.
 *
 * The two panels differ in every count, so a component reading the wrong one cannot pass.
 * The two accuracy tables disagree in sign on `all hours` for the same reason: that
 * disagreement is the actual finding, and a fixture where both tables agreed could not tell
 * a page rendering each from one rendering the first table twice.
 */
export const trackRecord: TrackRecord = {
  published_at: '2026-08-04',
  source: 'analysis/track_record/publish.py',
  held_out: {
    span: '2020/21-2025/26',
    basis: 'Hindcast',
    gold_days: 13,
    big_wave_seasons: 6,
    watch_or_better: {
      gold_days_called: 12,
      gold_days_in_panel: 13,
      days_flagged: 193,
      recall: 12 / 13,
      precision_lower_bound: 12 / 193,
      wasted_upper_bound: 1 - 12 / 193,
      days_wasted_upper_bound: 181,
      flags_per_big_wave_season: 193 / 6,
      // Both tiers carry a delivery since #87. Deliberately different figures from the Go
      // Call's below, so a component reading one tier's delivery into the other's row
      // renders a number that belongs somewhere else on the same page.
      delivered: {
        minimum_m: 2.72,
        median_m: 4.04,
        maximum_m: 8.14,
        above: [
          { metres: 3, days: 180, of_days: 193, share: 180 / 193 },
          { metres: 4, days: 101, of_days: 193, share: 101 / 193 },
          { metres: 5, days: 47, of_days: 193, share: 47 / 193 },
          { metres: 6, days: 23, of_days: 193, share: 23 / 193 },
        ],
      },
    },
    go_call: {
      gold_days_called: 9,
      gold_days_in_panel: 13,
      days_flagged: 43,
      recall: 9 / 13,
      precision_lower_bound: 9 / 43,
      wasted_upper_bound: 1 - 9 / 43,
      days_wasted_upper_bound: 34,
      flags_per_big_wave_season: 43 / 6,
      // The one tier the record publishes a delivery for. Every count here is distinct from
      // every other number in this fixture, so a component reading the wrong field renders a
      // number that appears nowhere it should and the assertion catches it.
      delivered: {
        minimum_m: 2.82,
        median_m: 3.8,
        maximum_m: 5.3,
        above: [
          { metres: 3, days: 39, of_days: 43, share: 39 / 43 },
          { metres: 4, days: 17, of_days: 43, share: 17 / 43 },
          { metres: 5, days: 5, of_days: 43, share: 5 / 43 },
          // A zero rung, because the real record has one at 6 m and a renderer that
          // filters empty rows would silently shorten the ladder.
          { metres: 6, days: 0, of_days: 43, share: 0 },
        ],
      },
    },
  },
  full_record: {
    span: '2011-2025',
    basis: 'Hindcast',
    gold_days: 38,
    big_wave_seasons: 16,
    watch_or_better: {
      gold_days_called: 33,
      gold_days_in_panel: 38,
      days_flagged: 574,
      recall: 33 / 38,
      precision_lower_bound: 33 / 574,
      wasted_upper_bound: 1 - 33 / 574,
      days_wasted_upper_bound: 541,
      flags_per_big_wave_season: 574 / 16,
    },
    go_call: {
      gold_days_called: 16,
      gold_days_in_panel: 38,
      days_flagged: 128,
      recall: 16 / 38,
      precision_lower_bound: 16 / 128,
      wasted_upper_bound: 1 - 16 / 128,
      days_wasted_upper_bound: 112,
      flags_per_big_wave_season: 128 / 16,
    },
  },
  // Exactly two rows carry a caveat, as in the real record: the strongest-looking figure on
  // the page, and the one aggregate whose sign does not survive #52's sensitivity check. The
  // rest are null, so a component that rendered a note against every row could not pass.
  scored: [
    {
      name: 'all hours',
      hours: 28426,
      baseline_mae_m: 0.1964,
      learned_mae_m: 0.207,
      gain_m: -0.0106,
      caveat: null,
    },
    {
      name: 'Gold Day hours',
      hours: 120,
      baseline_mae_m: 0.8851,
      learned_mae_m: 0.5636,
      gain_m: 0.3215,
      caveat: '120 hours across only 5 Gold Days.',
    },
    {
      name: '6 m and above',
      hours: 325,
      baseline_mae_m: 1.0313,
      learned_mae_m: 0.6211,
      gain_m: 0.4102,
      caveat: null,
    },
  ],
  served: [
    {
      name: 'all hours',
      hours: 28426,
      baseline_mae_m: 0.2197,
      learned_mae_m: 0.2971,
      gain_m: -0.0774,
      caveat: null,
    },
    {
      name: 'Combined Sea 3 m and above',
      hours: 4473,
      baseline_mae_m: 0.4278,
      learned_mae_m: 0.4005,
      gain_m: 0.0273,
      caveat: 'Not robust to the reconstruction assumption: +0.027 becomes -0.004.',
    },
    {
      name: 'under 2 m',
      hours: 15665,
      baseline_mae_m: 0.1562,
      learned_mae_m: 0.282,
      gain_m: -0.1258,
      caveat: null,
    },
    // Deliberately not 0.3555. A gain landing exactly on a rounding boundary makes the
    // rendered string depend on floating-point representation rather than on the component,
    // so the test would be asserting arithmetic nobody wrote.
    {
      name: '6 m and above',
      hours: 325,
      baseline_mae_m: 1.0109,
      learned_mae_m: 0.6549,
      gain_m: 0.356,
      caveat: null,
    },
  ],
  // Three lead times rather than the record's seven, and every figure distinct from every
  // other number in this fixture, so a component reading the wrong subset or the wrong row
  // renders a value that appears nowhere it should.
  range_calibration: {
    claimed: 0.9,
    // Distinct from every threshold elsewhere in this fixture, and deliberately not the Go
    // Call's height bar — a page describing it as that states something false.
    big_swell_from_m: 3.0,
    understates_because: 'The range this system prints is wider still.',
    rests_on: 'It rests on one partial Big-Wave Season.',
    leads: [
      {
        lead_days: 1,
        all_hours: {
          hours: 1593,
          covered: 0.9397,
          median_width_m: 1.0459,
          justified_width_m: 1.0459 * 0.822,
          widening_factor: 0.822,
        },
        big_swell: {
          hours: 807,
          covered: 0.9257,
          median_width_m: 1.6144,
          justified_width_m: 1.6144 * 0.9368,
          widening_factor: 0.9368,
        },
      },
      {
        lead_days: 4,
        all_hours: {
          hours: 1593,
          covered: 0.9849,
          median_width_m: 1.4717,
          justified_width_m: 1.4717 * 0.6028,
          widening_factor: 0.6028,
        },
        big_swell: {
          hours: 807,
          covered: 0.9777,
          median_width_m: 2.2867,
          justified_width_m: 2.2867 * 0.6563,
          widening_factor: 0.6563,
        },
      },
      {
        lead_days: 7,
        all_hours: {
          hours: 1593,
          covered: 0.9937,
          median_width_m: 2.1919,
          justified_width_m: 2.1919 * 0.5264,
          widening_factor: 0.5264,
        },
        big_swell: {
          hours: 807,
          covered: 0.9888,
          median_width_m: 3.0812,
          justified_width_m: 3.0812 * 0.5767,
          widening_factor: 0.5767,
        },
      },
    ],
  },
  gold_days_fitted: 25,
  gold_days_validated: 13,
  gold_days_total: 38,
  days: [
    {
      date: '2011-11-01',
      season: '2011/12',
      call: 'watch',
      peak_significant_wave_height_m: 3.4,
      gold_day: true,
      gold_tier: 'ratified',
    },
    {
      date: '2018-01-18',
      season: '2017/18',
      call: 'none',
      peak_significant_wave_height_m: 5.02,
      gold_day: true,
      gold_tier: 'ratified',
    },
    {
      date: '2024-12-30',
      season: '2024/25',
      call: 'go',
      peak_significant_wave_height_m: 4.61,
      gold_day: false,
      gold_tier: null,
    },
  ],
  issued: {
    calls_issued: 0,
    dates_covered: 0,
    go_calls_issued: 0,
    first_issued_at: null,
    last_issued_at: null,
  },
};

export const handlers = [
  http.get('*/api/conditions/forecast', () => HttpResponse.json(forecast)),
  http.get('*/api/conditions/current', () => HttpResponse.json(currentConditions)),
  http.get('*/api/track-record', () => HttpResponse.json(trackRecord)),
];
