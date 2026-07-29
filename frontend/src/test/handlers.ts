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

import type { CurrentConditions, Forecast } from '../api';

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
function hoursFor(date: string, swell: number, period: number, direction: number) {
  return Array.from({ length: 24 }, (_, hour) => ({
    at: `${date}T${String(hour).padStart(2, '0')}:00`,
    swell_height: { value: Number((swell + hour * 0.11).toFixed(2)), unit: 'm' },
    swell_period: { value: Number((period + hour * 0.13).toFixed(2)), unit: 's' },
    swell_direction: { value: direction + hour, unit: '°' },
    significant_wave_height: { value: Number((swell + 0.3 + hour * 0.07).toFixed(2)), unit: 'm' },
    wave_period: { value: Number((period + hour * 0.09).toFixed(2)), unit: 's' },
    wave_direction: { value: direction + hour * 2, unit: '°' },
    water_temperature: { value: Number((15.2 + hour * 0.01).toFixed(2)), unit: '°C' },
    air_temperature: { value: Number((13.4 + hour * 0.02).toFixed(2)), unit: '°C' },
    wind_speed: { value: Number((11 + hour * 0.3).toFixed(2)), unit: 'km/h' },
    wind_direction: { value: 115 + hour * 3, unit: '°' },
  }));
}

/** A quiet day, a huge day, and an easing day — so tests can prove a small day is shown
 * rather than hidden, and that height, period and direction stay separate. */
export const forecast: Forecast = {
  fetched_at: '2026-02-11T09:04:11.221000+00:00',
  days: [
    {
      date: '2026-02-12',
      peak_swell_height: { value: 1.4, unit: 'm' },
      swell_period_at_peak: { value: 8, unit: 's' },
      swell_direction_at_peak: { value: 250, unit: '°' },
      longest_swell_period: { value: 11, unit: 's' },
      hours: hoursFor('2026-02-12', 1.4, 8, 250),
    },
    {
      date: '2026-02-13',
      peak_swell_height: { value: 8.1, unit: 'm' },
      swell_period_at_peak: { value: 17, unit: 's' },
      swell_direction_at_peak: { value: 298, unit: '°' },
      longest_swell_period: { value: 21, unit: 's' },
      hours: hoursFor('2026-02-13', 8.1, 17, 298),
    },
    {
      date: '2026-02-14',
      // 5.7 of a 8.1 peak is 70% — deliberately inside the middle tier, so a test can
      // prove that tier exists rather than only its two extremes.
      peak_swell_height: { value: 5.7, unit: 'm' },
      swell_period_at_peak: { value: 12, unit: 's' },
      swell_direction_at_peak: { value: 280, unit: '°' },
      longest_swell_period: { value: 14, unit: 's' },
      hours: hoursFor('2026-02-14', 3.5, 12, 280),
    },
  ],
};

export const handlers = [
  http.get('*/api/conditions/forecast', () => HttpResponse.json(forecast)),
  http.get('*/api/conditions/current', () => HttpResponse.json(currentConditions)),
];
