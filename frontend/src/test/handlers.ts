/**
 * Default API responses for the frontend suite.
 *
 * Tests import these fixtures and assert against them, so an assertion cannot
 * accidentally match something the component renders statically — that mistake made
 * this suite's only loaded-state test pass against a component that fetched nothing.
 */

import { http, HttpResponse } from 'msw';

import type { CurrentConditions } from '../api';

export const placeholderConditions: CurrentConditions = {
  placeholder: true,
  location: 'Praia do Norte, Nazare',
  message: 'Wired end to end. No conditions are being measured yet.',
};

export const handlers = [
  http.get('*/api/conditions/current', () => HttpResponse.json(placeholderConditions)),
];
