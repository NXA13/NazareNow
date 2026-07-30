/**
 * Tests for the interface, driven through what a user actually sees.
 *
 * This is one of the project's two agreed test seams. The API is mocked at the network
 * boundary; component internals, state management and styling are not asserted, so the
 * implementation behind these behaviours can be rewritten freely.
 *
 * Assertions target values imported from the fixtures rather than text matched loosely.
 * Two tests have already shipped here that asserted nothing: one matched the page's own
 * static subtitle, another matched the static word "Observed" while the date formatter
 * was broken. Every assertion below must fail if the API's value stops being rendered.
 */

import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { App } from './App';
import { currentConditions } from './test/handlers';
import { server } from './test/server';

/** Find the labelled block for one reading, e.g. "Swell height". */
async function reading(label: string) {
  return within(await screen.findByRole('group', { name: new RegExp(`^${label}$`, 'i') }));
}

/** Every reading the API returns. A test below pins this list to the API type, so a
 * reading cannot be added to the contract without also being displayed and asserted. */
const READINGS: [string, keyof typeof currentConditions][] = [
  ['Swell height', 'swell_height'],
  ['Swell period', 'swell_period'],
  ['Swell direction', 'swell_direction'],
  ['Significant wave height', 'significant_wave_height'],
  ['Wave period', 'wave_period'],
  ['Wave direction', 'wave_direction'],
  ['Wind speed', 'wind_speed'],
  ['Wind direction', 'wind_direction'],
  ['Air temperature', 'air_temperature'],
  ['Water temperature', 'water_temperature'],
];

/** Fields describing the observation rather than being readings. */
const METADATA = ['observed_at', 'fetched_at', 'latitude', 'longitude'];

describe('current conditions', () => {
  it('covers every reading the API returns', () => {
    // Without this, READINGS is just a hand-written list: an eleventh field could be
    // added to the API and the fixture and still pass 14 of 14.
    const fromApi = Object.keys(currentConditions).filter((key) => !METADATA.includes(key));
    const covered = READINGS.map(([, key]) => key as string);

    expect(covered.sort()).toEqual(fromApi.sort());
  });

  it.each(READINGS)('shows %s with its unit', async (label, key) => {
    const expected = currentConditions[key] as { value: number; unit: string };

    render(<App />);

    const block = await reading(label);
    expect(block.getByText(String(expected.value))).toBeInTheDocument();
    expect(block.getByText(expected.unit)).toBeInTheDocument();
  });

  it('shows directions as a compass bearing as well as degrees', async () => {
    // 298 degrees is west-north-west; 115 is east-south-east. A reader should not have
    // to know the convention to understand where the swell is coming from.
    render(<App />);

    expect((await reading('Swell direction')).getByText('WNW')).toBeInTheDocument();
    expect((await reading('Wind direction')).getByText('ESE')).toBeInTheDocument();
  });

  it('shows when the data was observed and when it was fetched', async () => {
    // Timezone is pinned to UTC in vite.config.ts, so these are deterministic. The
    // fixture is observed at 09:00 and fetched at 09:04 — asserting both proves the
    // formatter ran and that the two timestamps are not being conflated.
    render(<App />);

    const freshness = await screen.findByTestId('freshness');
    expect(freshness).toHaveTextContent(/observed/i);
    expect(freshness).toHaveTextContent(/09:00/);
    expect(freshness).toHaveTextContent(/09:04/);
    expect(freshness).toHaveTextContent(/13/);
  });

  it('does not claim any reading was measured', async () => {
    // The page said "Swell and sea measured at 39.54°N, 9.21°W — roughly 15km offshore,
    // near the head of the Nazaré Canyon". Nothing on it is an observation: every figure
    // is Open-Meteo model output at a grid point, and no buoy reading reaches the live
    // system — Monican02's record lives only in analysis/, for a model not yet built.
    // Describing a modelled figure as measured invites a reader to trust it further than
    // it deserves. Nothing asserted this wording, so the claim went unguarded.
    render(<App />);

    const provenance = await screen.findByTestId('provenance');
    expect(provenance).toHaveTextContent(/modelled/i);
    expect(provenance).toHaveTextContent(/not measured/i);
    expect(provenance).not.toHaveTextContent(/sea measured at/i);
  });

  it('exposes the raw timestamps in machine-readable form', async () => {
    render(<App />);

    const freshness = await screen.findByTestId('freshness');
    const times = within(freshness).getAllByText(/\d{2}:\d{2}/);
    expect(times[0]).toHaveAttribute('datetime', currentConditions.observed_at);
  });

  it('tells the user when no conditions have been ingested yet', async () => {
    // The backend returns 503 rather than zeros when its store is empty. A flat, calm
    // ocean is a plausible-looking lie; this must read as a fault.
    server.use(http.get('*/api/conditions/current', () => new HttpResponse(null, { status: 503 })));

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i);
    expect(screen.queryByRole('group', { name: /swell height/i })).toBeNull();
  });
});
