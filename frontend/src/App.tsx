import { useEffect, useState } from 'react';

import { fetchCurrentConditions, type CurrentConditions, type Reading } from './api';
import { ForecastRange } from './Forecast';
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
          {/* Above everything, not in the footer. ADR 0005 promises the site stays up and
              honest when the provider is unreachable — and a timestamp at the bottom of
              the page is not honest enough on its own. Someone deciding whether to book a
              flight should learn the data is old before they read the data, not after.
              Whether it *is* old is the backend's judgement, not this layer's. */}
          {state.conditions.stale && (
            <p role="alert" className="alert stale">
              <strong>These conditions are out of date.</strong> No forecast has been retrieved for
              at least {state.conditions.stale_after_hours} hours, so this is the last data we
              received rather than the current picture. Treat the calls below as history, not
              advice.
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

          {/* Swell is the travelled component the canyon amplifies; the combined sea also
              includes locally raised wind waves. CONTEXT.md keeps the two apart. */}
          <section aria-labelledby="combined-heading">
            <h2 id="combined-heading">Combined sea</h2>
            <dl className="readings">
              <ReadingBlock
                label="Significant wave height"
                reading={state.conditions.significant_wave_height}
              />
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

          <ForecastRange />

          <footer>
            <p data-testid="freshness">
              Observed{' '}
              <time dateTime={state.conditions.observed_at}>
                {formatTimestamp(state.conditions.observed_at)}
              </time>
              , fetched{' '}
              <time dateTime={state.conditions.fetched_at}>
                {formatTimestamp(state.conditions.fetched_at)}
              </time>
              .
            </p>
            {/* "Measured" was a lie, and a flattering one. Nothing on this page is an
                observation: every figure is Open-Meteo model output at a grid point, and no
                buoy reading reaches the live system at all — Monican02's record exists only
                in the analysis directory, for training a model that does not exist yet. A
                modelled figure described as measured invites a reader to trust it more than
                it deserves, which is the whole failure this project is built to avoid. */}
            <p className="provenance" data-testid="provenance">
              Swell and sea are <strong>modelled</strong>, not measured — Open-Meteo's forecast for{' '}
              {state.conditions.latitude.toFixed(2)}°N,{' '}
              {Math.abs(state.conditions.longitude).toFixed(2)}
              °W, roughly 15km offshore near the head of the Nazaré Canyon. No buoy reading reaches
              this page. Wind and air temperature come from the nearest land forecast cell, which is
              not the same point.
            </p>
          </footer>
        </>
      )}
    </main>
  );
}
