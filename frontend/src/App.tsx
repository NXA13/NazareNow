import { useEffect, useState } from 'react';

import { fetchCurrentConditions, type CurrentConditions } from './api';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; conditions: CurrentConditions }
  | { status: 'failed' };

export function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let active = true;
    fetchCurrentConditions()
      .then((conditions) => active && setState({ status: 'loaded', conditions }))
      .catch(() => active && setState({ status: 'failed' }));
    return () => {
      active = false;
    };
  }, []);

  return (
    <main>
      <h1>NazareNow</h1>
      <p>When will Praia do Norte produce giant waves?</p>

      {state.status === 'loading' && <p>Loading conditions...</p>}

      {state.status === 'failed' && (
        <p role="alert">Could not load conditions. The forecast service may be unavailable.</p>
      )}

      {state.status === 'loaded' && (
        <section>
          {/* The placeholder warning is not decoration. Until a Pipeline Run is
              actually producing forecasts, a page that looked authoritative would
              mislead — so the flag from the API is surfaced, not hidden. */}
          {state.conditions.placeholder && (
            <p role="status">
              This is not real data. The system is wired end to end but measures nothing yet.
            </p>
          )}
          <h2>{state.conditions.location}</h2>
          <p>{state.conditions.message}</p>
        </section>
      )}
    </main>
  );
}
