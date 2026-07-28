/**
 * Tests for the interface, driven through what a user actually sees.
 *
 * This is one of the project's two agreed test seams. The API is mocked at the network
 * boundary; component internals, state management and styling are not asserted, so the
 * implementation behind these behaviours can be rewritten freely.
 */

import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { App } from './App';
import { server } from './test/server';

const placeholderConditions = {
  placeholder: true,
  location: 'Praia do Norte, Nazare',
  message: 'Wired end to end. No conditions are being measured yet.',
};

describe('the conditions page', () => {
  it('shows what the API reports for Praia do Norte', async () => {
    server.use(
      http.get('*/api/conditions/current', () => HttpResponse.json(placeholderConditions)),
    );

    render(<App />);

    expect(await screen.findByText(/Praia do Norte/)).toBeInTheDocument();
  });

  it('warns the user when the data is only a placeholder', async () => {
    // Nothing real is wired up yet. A page that looked like a working forecast would
    // be worse than one that plainly says it is not.
    server.use(
      http.get('*/api/conditions/current', () => HttpResponse.json(placeholderConditions)),
    );

    render(<App />);

    expect(await screen.findByRole('status')).toHaveTextContent(/not real data/i);
  });

  it('tells the user when conditions cannot be loaded', async () => {
    server.use(http.get('*/api/conditions/current', () => new HttpResponse(null, { status: 500 })));

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i);
  });
});
