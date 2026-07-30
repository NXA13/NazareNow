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

import type { CallStatus, CurrentConditions, Forecast } from '../api';

export const currentConditions: CurrentConditions = {
  observed_at: '2026-02-13T09:00',
  fetched_at: '2026-02-13T09:04:11.221000+00:00',
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
) {
  const hours = hoursFor(date, peak, longestPeriod, direction);
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
              '3 of 24 forecast hours match every condition',
            ],
            // Its own object with its own value. Sharing peak_swell_height's object made
            // rendering the wrong one undetectable, and they are different quantities:
            // CONTEXT.md lists swell height under significant wave height's avoided synonyms.
            predicted_significant_wave_height: {
              value: Number((peakHour.swell_height.value + 0.4).toFixed(2)),
              unit: 'm',
            },
          },
    peak_swell_height: peakHour.swell_height,
    swell_period_at_peak: peakHour.swell_period,
    swell_direction_at_peak: peakHour.swell_direction,
    longest_swell_period: longestHour.swell_period,
    hours,
  };
}

/** A quiet day, a huge day, and an easing day — so tests can prove a small day is shown
 * rather than hidden, and that height, period and direction stay separate. */
export const forecast: Forecast = {
  fetched_at: '2026-02-11T09:04:11.221000+00:00',
  amplification_model: 'heuristic-baseline',
  calibrated: false,
  days: [
    dayFrom('2026-02-12', 1.4, 8, 250, 'confirmed', 1),
    // Base chosen so the peak hour (15:00, +75 degrees) lands on 298 = WNW, which the
    // tests assert as a literal rather than recomputing it with compassPoint.
    dayFrom('2026-02-13', 8.1, 17, 223, 'go', 4),
    dayFrom('2026-02-14', 5.7, 12, 280, 'watch', 9),
  ],
};

export const handlers = [
  http.get('*/api/conditions/forecast', () => HttpResponse.json(forecast)),
  http.get('*/api/conditions/current', () => HttpResponse.json(currentConditions)),
];
