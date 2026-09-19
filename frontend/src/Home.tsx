/**
 * The forecast page: the current conditions, the days ahead, and where the figures came from.
 *
 * Lifted out of `App.tsx` whole when v2 put the site behind a router (#113), and given its two
 * columns by #115 — the forecast on the left, the map on the right, matching its height.
 *
 * **Most of the left column is still v1's.** #115 built the shell and moved nothing into it;
 * #117 has since turned the day cards into one row per day. What is left is the verdict and the
 * four gated tiles (#116), the hours taking the day list's slot (#118), and moving the teaching
 * material off this page (#119).
 *
 * So this page does not yet keep the no-scroll promise the shell is built for, and #117 did not
 * bring it closer: sixteen days as rows are taller than sixteen days packed into a grid, which
 * is the cost of a row carrying four things instead of two. The saving is in #116 and #119, and
 * `e2e/layout.spec.ts` carries the arithmetic. What the shell guarantees today is that neither
 * column scrolls on its own and the two stay level; what it cannot guarantee yet is that their
 * content fits.
 */

import { useEffect, useState, type ReactNode } from 'react';

import { fetchCurrentConditions, type CurrentConditions, type Reading } from './api';
import { ForecastRange } from './Forecast';
import { MapSlot } from './MapSlot';
import { compassPoint, formatTimestamp, formatValue } from './format';

type LoadState =
  | { status: 'loading' }
  | { status: 'loaded'; conditions: CurrentConditions }
  | { status: 'failed' };

/** One companion reading, riding small on the tile whose wave field it belongs to.
 *
 * Its own `group` with its own name, like the headline reading above it, so a screen reader
 * hears "wave period, 11.4 seconds" rather than four bare numbers under one label — and so a
 * test can assert that the Combined Sea's period is on the Combined Sea's tile rather than
 * that the figure appears on the page somewhere.
 */
function Companion({
  label,
  reading,
  bearing = false,
}: {
  label: string;
  reading: Reading;
  bearing?: boolean;
}) {
  return (
    <div className="companion" role="group" aria-label={label}>
      <dt>{label}</dt>
      <dd>
        <span className="value">{formatValue(reading.value)}</span>
        <span className="unit">{reading.unit}</span>
        {bearing && <span className="bearing">{compassPoint(reading.value)}</span>}
      </dd>
    </div>
  );
}

/** One tile: a gated quantity at the size of a headline, and the rest of its wave field small. */
function Tile({
  slug,
  label,
  reading,
  bearing = false,
  children,
}: {
  slug: string;
  label: string;
  reading: Reading;
  bearing?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="tile" data-testid={`tile-${slug}`}>
      {/* The gated reading is its own group rather than the tile being one. A tile that was the
          group would contain its companions' values too, so "the swell period block shows 13.75"
          would be satisfied by a tile showing 13.75 anywhere inside it. */}
      <dl className="tile-headline" role="group" aria-label={label}>
        <dt>{label}</dt>
        <dd>
          <span className="value">{formatValue(reading.value)}</span>
          <span className="unit">{reading.unit}</span>
          {bearing && <span className="bearing">{compassPoint(reading.value)}</span>}
        </dd>
      </dl>
      {children && <dl className="companions">{children}</dl>}
    </div>
  );
}

/**
 * The four tiles, and the six readings that are not on them (#116).
 *
 * `/api/conditions/current` sends ten readings and the design shows four tiles. **The four are
 * not an arbitrary selection: they are exactly the quantities a Go Call is gated on**, which is
 * the rule that makes the row legible rather than decorative — the tile row is what the call is
 * decided on, at the size of a headline.
 *
 * **The other six are not dropped.** Each tile carries the rest of its own wave field, small,
 * and the two temperatures gate nothing so they take one quiet line underneath. They were nearly
 * declared unread, and were not, because the pipeline would then go on fetching and storing two
 * numbers the site never shows — which is worse than one short line. All sixteen fields of
 * `CurrentConditions` stay in `every-field-is-read.test.tsx`'s read arm; none was argued onto
 * the unread list to make this ticket pass.
 *
 * **The one placement that carries a claim** is the Swell's own height, which sits under the
 * swell period rather than beside the Significant Wave Height. CONTEXT.md keeps the two apart:
 * Swell is only the travelled component and is what the canyon amplifies, while the Combined Sea
 * — which Significant Wave Height describes — also includes locally raised wind waves. A reader
 * who takes one for the other has misread the two quantities the domain is most careful about.
 */
function ConditionTiles({ conditions }: { conditions: CurrentConditions }) {
  return (
    <>
      <div className="tiles" data-testid="tiles">
        <Tile
          slug="significant-wave-height"
          label="Significant wave height"
          reading={conditions.significant_wave_height}
        >
          {/* This tile *is* the Combined Sea, so the Combined Sea's period and direction ride
              on it rather than on the Swell's tiles. */}
          <Companion label="Wave period" reading={conditions.wave_period} />
          <Companion label="Wave direction" reading={conditions.wave_direction} bearing />
        </Tile>

        <Tile slug="swell-period" label="Swell period" reading={conditions.swell_period}>
          <Companion label="Swell height" reading={conditions.swell_height} />
        </Tile>

        <Tile
          slug="swell-direction"
          label="Swell direction"
          reading={conditions.swell_direction}
          bearing
        />

        <Tile slug="wind-speed" label="Wind speed" reading={conditions.wind_speed}>
          <Companion label="Wind direction" reading={conditions.wind_direction} bearing />
        </Tile>
      </div>

      {/* Neither temperature gates anything, so neither gets a tile: a tile is the page saying
          "the call turns on this", and a sea temperature decides nothing about whether to fly. */}
      <dl className="temperatures" data-testid="temperatures">
        <Companion label="Water temperature" reading={conditions.water_temperature} />
        <Companion label="Air temperature" reading={conditions.air_temperature} />
      </dl>
    </>
  );
}

export function Home() {
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
    <div className="home">
      {/* The left column, and everything that was on this page before it had columns. */}
      <div className="home-forecast">
        {state.status === 'loading' && <p>Loading conditions...</p>}

        {state.status === 'failed' && (
          <p role="alert" className="alert">
            Could not load conditions. The forecast service may be unavailable, or no pipeline run
            has stored anything yet.
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
                <strong>These conditions are out of date.</strong> No forecast has been retrieved
                for at least {state.conditions.stale_after_hours} hours, so this is the last data we
                received rather than the current picture. Treat the calls below as history, not
                advice.
              </p>
            )}

            <ForecastRange tiles={<ConditionTiles conditions={state.conditions} />} />

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
                Swell and sea are <strong>modelled</strong>, not measured — Open-Meteo's forecast
                for {state.conditions.latitude.toFixed(2)}°N,{' '}
                {Math.abs(state.conditions.longitude).toFixed(2)}
                °W, roughly 15km offshore near the head of the Nazaré Canyon. No buoy reading
                reaches this page. Wind and air temperature come from the nearest land forecast
                cell, which is not the same point.
              </p>
            </footer>
          </>
        )}
      </div>

      {/* The right column. It exists in every state, including before the conditions load and
          after they fail: a column that appeared only on success would make the page jump at
          the moment a reader is deciding whether to trust it. */}
      <div className="home-map">
        <MapSlot />
      </div>
    </div>
  );
}
