/**
 * The map's slot — a placeholder until #121, the sea floor since, and the swell since #122.
 *
 * The right column existed before its contents did, so the shell's promises — two columns of
 * equal height, a stable split, the page not scrolling on desktop — could be tested before there
 * was anything expensive inside it. That is why #115 came first, and the placeholder it held is
 * gone now: `Bathymetry` draws the canyon from soundings and `Crests` bends today's swell over
 * it.
 *
 * **The note under the figure is not decoration, and two of its sentences are required.** The
 * ticket and the spec both say they travel together wherever this map is explained: the crest
 * *shape* is computed and the crest *spacing* is exaggerated, and the model is refraction alone.
 * `Bathymetry.test.tsx` fails if either goes missing. The second matters more now than it did
 * when the crests were going to be precomputed — a model that runs live, on the reader's own
 * machine, against this morning's sea, is far easier to mistake for a forecast of the surf.
 *
 * It is SVG that fits whatever box it is given, which is why this slot still has no aspect ratio
 * of its own on desktop: it takes the height of the column beside it.
 */

import { Bathymetry } from './Bathymetry';
import { WindLegend } from './Wind';
import type { ConditionsGrid } from './api';
import { formatTimestamp } from './format';
import type { Swell } from './refraction';

interface MapSlotProps {
  swell: Swell | null;
  grid: ConditionsGrid | null;
  /** True once the grid request has failed, which is distinct from it not having arrived. */
  windUnavailable: boolean;
}

export function MapSlot({ swell, grid, windUnavailable }: MapSlotProps) {
  /**
   * **A grid with no points in it counts as no grid.**
   *
   * The endpoint answers 503 rather than an empty grid precisely because "a two hundred
   * carrying no points is a map a reader cannot tell from a map of a flat calm" — but that is
   * the backend's promise, and a page that draws nothing and says nothing whenever the promise
   * is broken is trusting a contract instead of checking one. A 200 with `points: []` gets the
   * same sentence a 503 gets.
   */
  const haveWind = grid !== null && grid.points.length > 0;
  const sayMissing = windUnavailable || (grid !== null && !haveWind);

  /**
   * **Only over wind that was actually drawn.** Calling a picture out of date is qualifying
   * the picture, and where there are no darts the sentence below covers it instead — one
   * caveat per thing gone wrong, never two describing the same absence.
   */
  const sayOld = haveWind && (grid.stale || grid.refresh_failed);

  return (
    <aside className="map-slot" aria-label="Map">
      <Bathymetry swell={swell} grid={haveWind ? grid : null} />

      {/* The key, only where there is wind to key. It drifts at the rates it names, from the
          same function the map uses, so it cannot disagree with the darts above it. */}
      {haveWind ? <WindLegend /> : null}

      {/* **Said, not left blank.** The endpoint answers 503 rather than an empty grid because
          "a two hundred carrying no points is a map a reader cannot tell from a map of a flat
          calm" — and a map that silently lost its darts is the same lie one layer up. */}
      {sayMissing ? (
        <p className="map-slot-note map-slot-note-missing">
          <strong>Wind unavailable.</strong> The map is showing the sea floor and the swell only —
          not a calm.
        </p>
      ) : null}
      {/* **The gap #139 filed, closed at the end a reader stands at.**

          The grid is dated by its own fetch rather than by the run that finished last, so the
          wind here can be two cycles older than the forecast in the column beside it and the
          two stamps are both honest. That is right, and it left this map drawing six-hour-old
          darts with nothing on it to say so.

          **Two clauses, because they are two facts and they can disagree.** `stale` is the
          backend's arithmetic on `fetched_at` against six hours — two whole cycles, so that a
          single provider hiccup is not dressed up as a warning. `refresh_failed` is not
          arithmetic at all: the run that tried and lost recorded the endpoint and the failure
          kind the instant it happened, and this is that record reaching a human. It can be true
          while `stale` is still false, which is how a reader learns inside one cycle rather than
          two — and the reason folding them into one sentence would throw the fix away. ADR 0018.

          `role="status"` rather than `alert`: this qualifies a picture already on the page, and
          it does not interrupt. */}
      {sayOld ? (
        <p role="status" className="map-slot-note map-slot-note-old">
          <strong>This wind is out of date.</strong> It arrived{' '}
          <time dateTime={grid.fetched_at}>{formatTimestamp(grid.fetched_at)}</time>.
          {grid.stale
            ? ` Nothing newer has arrived for at least ${grid.stale_after_hours} hours.`
            : ''}
          {grid.refresh_failed ? ' A refresh since then failed.' : ''} The darts are the last wind
          we received, not the current one.
        </p>
      ) : null}
      {/* Outside the figure, and saying the things a reader could otherwise get wrong: where
          the shape came from, what the drawn spacing is and is not, and how little of the sea
          this model contains. ADR 0012's rule is that prose says whether a number is current;
          the same obligation applies to a picture, and this picture is now half permanent and
          half live, which is the harder case. */}
      <p className="map-slot-note">
        The sea floor, from <strong>GEBCO soundings</strong> — the Nazaré Canyon reaching almost to
        the beach. The crests are today&rsquo;s swell bent over it:{' '}
        <strong>their shape is computed, their spacing is exaggerated</strong> — the true spacing
        here would be about 160 crests. The model is <strong>refraction alone</strong>. It ignores
        diffraction, reflection, currents and non-linearity, and a real swell is a spread of periods
        and directions rather than the single one drawn. It does not say how big the waves will be.
      </p>
    </aside>
  );
}
