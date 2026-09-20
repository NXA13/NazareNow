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
import type { Swell } from './refraction';

interface MapSlotProps {
  swell: Swell | null;
  grid: ConditionsGrid | null;
  /** True once the grid request has failed, which is distinct from it not having arrived. */
  windUnavailable: boolean;
}

export function MapSlot({ swell, grid, windUnavailable }: MapSlotProps) {
  return (
    <aside className="map-slot" aria-label="Map">
      <Bathymetry swell={swell} grid={grid} />

      {/* The key, only where there is wind to key. It drifts at the rates it names, from the
          same function the map uses, so it cannot disagree with the darts above it. */}
      {grid ? <WindLegend /> : null}

      {/* **Said, not left blank.** The endpoint answers 503 rather than an empty grid because
          "a two hundred carrying no points is a map a reader cannot tell from a map of a flat
          calm" — and a map that silently lost its darts is the same lie one layer up. */}
      {windUnavailable ? (
        <p className="map-slot-note map-slot-note-missing">
          <strong>Wind unavailable.</strong> The map is showing the sea floor and the swell only —
          not a calm.
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
