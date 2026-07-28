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

import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { App } from './App';
import { placeholderConditions } from './test/handlers';
import { server } from './test/server';

describe('the conditions page', () => {
  it('shows the location and message the API reported', async () => {
    render(<App />);

    // A heading, not any text: the static subtitle also mentions Praia do Norte, and
    // matching it would make this assertion pass without the API being involved.
    expect(
      await screen.findByRole('heading', { name: placeholderConditions.location }),
    ).toBeInTheDocument();
    expect(screen.getByText(placeholderConditions.message)).toBeInTheDocument();
  });

  it('warns the user when the data is only a placeholder', async () => {
    // Nothing real is wired up yet. A page that looked like a working forecast would
    // be worse than one that plainly says it is not.
    render(<App />);

    expect(await screen.findByRole('status')).toHaveTextContent(/not real data/i);
  });

  it('does not warn when the API is serving genuine measurements', async () => {
    server.use(
      http.get('*/api/conditions/current', () =>
        HttpResponse.json({ ...placeholderConditions, placeholder: false }),
      ),
    );

    render(<App />);

    await screen.findByRole('heading', { name: placeholderConditions.location });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('tells the user when conditions cannot be loaded', async () => {
    server.use(http.get('*/api/conditions/current', () => new HttpResponse(null, { status: 500 })));

    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not load/i);
    expect(screen.queryByRole('heading', { name: placeholderConditions.location })).toBeNull();
  });
});
