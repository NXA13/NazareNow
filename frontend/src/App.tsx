import { useEffect, useState } from 'react';

import { fetchCurrentConditions, type CurrentConditions, type Reading } from './api';
import { compassPoint, formatTimestamp, formatValue } from './format';
import './App.css';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; conditions: CurrentConditions }
  | { status: 'failed' };

/**
 * One reading, labelled and carrying its unit.
 *
 * Rendered as a `group` with an accessible name so the label and its value are bound
 * together — for screen readers, and so tests can assert "the swell height block shows
 * 8.1" rather than "8.1 appears somewhere on the page".
 */
function ReadingBlock({
  label,
  reading,
  bearing = false,
}: {
  label: string;
  reading: Reading;
  bearing?: boolean;
}) {
  return (
    <div className="reading" role="group" aria-label={label}>
      <dt>{label}</dt>
      <dd>
        <span className="value">{formatValue(reading.value)}</span>
        <span className="unit">{reading.unit}</span>
        {bearing && <span className="bearing">{compassPoint(reading.value)}</span>}
      </dd>
    </div>
  );
}

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
      <header>
        <h1>NazareNow</h1>
        <p className="tagline">When will Praia do Norte produce giant waves?</p>
      </header>

      {state.status === 'loading' && <p>Loading conditions...</p>}

      {state.status === 'failed' && (
        <p role="alert" className="alert">
          Could not load conditions. The forecast service may be unavailable, or no pipeline run has
          stored anything yet.
        </p>
      )}

      {state.status === 'loaded' && (
        <>
          {/* Until a Pipeline Run supplies real measurements, say so plainly. A page
              that looked authoritative while showing stand-in values would mislead. */}
          {state.conditions.placeholder && (
            <p role="status" className="alert">
              This is not real data. The system is wired end to end but measures nothing yet.
            </p>
          )}

          <section aria-labelledby="swell-heading">
            <h2 id="swell-heading">Swell</h2>
            <dl className="readings">
              <ReadingBlock label="Swell height" reading={state.conditions.swell_height} />
              <ReadingBlock label="Swell period" reading={state.conditions.swell_period} />
              <ReadingBlock
                label="Swell direction"
                reading={state.conditions.swell_direction}
                bearing
              />
            </dl>
          </section>

          <section aria-labelledby="sea-heading">
            <h2 id="sea-heading">Sea state</h2>
            <dl className="readings">
              <ReadingBlock label="Wave height" reading={state.conditions.wave_height} />
              <ReadingBlock label="Wave period" reading={state.conditions.wave_period} />
              <ReadingBlock
                label="Wave direction"
                reading={state.conditions.wave_direction}
                bearing
              />
            </dl>
          </section>

          <section aria-labelledby="wind-heading">
            <h2 id="wind-heading">Wind and temperature</h2>
            <dl className="readings">
              <ReadingBlock label="Wind speed" reading={state.conditions.wind_speed} />
              <ReadingBlock
                label="Wind direction"
                reading={state.conditions.wind_direction}
                bearing
              />
              <ReadingBlock label="Air temperature" reading={state.conditions.air_temperature} />
              <ReadingBlock
                label="Water temperature"
                reading={state.conditions.water_temperature}
              />
            </dl>
          </section>

          <footer data-testid="freshness">
            <p>
              Observed {formatTimestamp(state.conditions.observed_at)}, fetched{' '}
              {formatTimestamp(state.conditions.fetched_at)}.
            </p>
            <p className="provenance">
              Measured at {state.conditions.latitude.toFixed(2)}N,{' '}
              {Math.abs(state.conditions.longitude).toFixed(2)}W — roughly 15km offshore, near the
              head of the Nazare Canyon.
            </p>
          </footer>
        </>
      )}
    </main>
  );
}
