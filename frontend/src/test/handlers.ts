/**
 * Default API responses for the frontend suite.
 *
 * Tests import these fixtures and assert against them, so an assertion cannot
 * accidentally match something the component renders statically — that mistake made
 * this suite's only loaded-state test pass against a component that fetched nothing.
 *
 * The values describe a genuinely large day so that assertions about formatting are
 * exercised on realistic numbers rather than zeros.
 */

import { http, HttpResponse } from 'msw';

import type { CurrentConditions } from '../api';

export const currentConditions: CurrentConditions = {
  observed_at: '2026-02-13T09:00',
  fetched_at: '2026-02-13T09:04:11.221000+00:00',
  latitude: 39.541664,
  longitude: -9.208328,
  placeholder: false,
  swell_height: { value: 8.1, unit: 'm' },
  swell_period: { value: 17.0, unit: 's' },
  swell_direction: { value: 298, unit: '°' },
  wave_height: { value: 8.4, unit: 'm' },
  wave_period: { value: 16.2, unit: 's' },
  wave_direction: { value: 295, unit: '°' },
  water_temperature: { value: 15.2, unit: '°C' },
  air_temperature: { value: 13.4, unit: '°C' },
  wind_speed: { value: 11.0, unit: 'km/h' },
  wind_direction: { value: 115, unit: '°' },
};

export const handlers = [
  http.get('*/api/conditions/current', () => HttpResponse.json(currentConditions)),
];
