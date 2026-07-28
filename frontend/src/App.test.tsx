/**
 * Tests for the interface, driven through what a user actually sees.
 *
 * This is one of the project's two agreed test seams. The API is mocked at the network
 * boundary; component internals, state management and styling are not asserted, so the
 * implementation behind these behaviours can be rewritten freely.
 *
 * Assertions target values imported from the fixtures rather than text matched loosely.
 * An earlier version asserted `findByText(/Praia do Norte/)`, which silently matched the
 * page's own static subtitle — it passed against a component that fetched nothing at
 * all, and against an API returning a 500.
 */

import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { App } from './App';
import { currentConditions } from './test/handlers';
import { server } from './test/server';

/** Find the labelled block for one reading, e.g. "Swell height". */
async function reading(label: string) {
  return within(await screen.findByRole('group', { name: new RegExp(label, 'i') }));
}

describe('current conditions', () => {
  it('shows swell height with its unit', async () => {
    render(<App />);

    const block = await reading('swell height');
    expect(block.getByText('8.1')).toBeInTheDocument();
    expect(block.getByText('m')).toBeInTheDocument();
  });

  it('shows swell period and wind speed with their units', async () => {
    render(<App />);

    expect((await reading('swell period')).getByText('17')).toBeInTheDocument();
    expect((await reading('swell period')).getByText('s')).toBeInTheDocument();
    expect((await reading('wind speed')).getByText('11')).toBeInTheDocument();
    expect((await reading('wind speed')).getByText('km/h')).toBeInTheDocument();
  });

  it('shows air and water temperature separately', async () => {
    render(<App />);

    expect((await reading('water temperature')).getByText('15.2')).toBeInTheDocument();
    expect((await reading('air temperature')).getByText('13.4')).toBeInTheDocument();
  });

  it('shows directions as a compass bearing as well as degrees', async () => {
    // 298 degrees is west-north-west; 115 is east-south-east. A reader should not have
    // to know the convention to understand where the swell is coming from.
    render(<App />);

    const swell = await reading('swell direction');
    expect(swell.getByText(/WNW/)).toBeInTheDocument();
    expect(swell.getByText(/298/)).toBeInTheDocument();

    const wind = await reading('wind direction');
    expect(wind.getByText(/ESE/)).toBeInTheDocument();
  });

  it('says when the data was last refreshed', async () => {
    render(<App />);

    expect(await screen.findByTestId('freshness')).toHaveTextContent(/observed/i);
  });

  it('does not warn about placeholder data once conditions are real', async () => {
    render(<App />);

    await reading('swell height');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('warns when the API is still serving a placeholder', async () => {
    server.use(
      http.get('*/api/conditions/current', () =>
        HttpResponse.json({ ...currentConditions, placeholder: true }),
      ),
    );

    render(<App />);

    expect(await screen.findByRole('status')).toHaveTextContent(/not real data/i);
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
