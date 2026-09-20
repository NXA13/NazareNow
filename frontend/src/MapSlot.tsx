/**
 * The map's slot — a placeholder until #121, and the sea floor since.
 *
 * The right column existed before its contents did, so the shell's promises — two columns of
 * equal height, a stable split, the page not scrolling on desktop — could be tested before there
 * was anything expensive inside it. That is why #115 came first, and the placeholder it held is
 * gone now: `Bathymetry` draws the canyon from soundings.
 *
 * **What is here is the base only.** The swell refracting over the canyon is #122 and the wind
 * across it is #123, so this map is a sea floor and says nothing about today. That is the line
 * the caption under it has to hold: the tone this map is drawn in carries depth, and colour on
 * it will mean live data when there is any. A reader must not take a permanent feature of the
 * sea bed for a forecast.
 *
 * It is SVG that fits whatever box it is given, which is why this slot still has no aspect ratio
 * of its own on desktop: it takes the height of the column beside it.
 */

import { Bathymetry } from './Bathymetry';

export function MapSlot() {
  return (
    <aside className="map-slot" aria-label="Map">
      <Bathymetry />
      {/* Outside the figure, and saying the two things a reader could otherwise get wrong: that
          this is the sea bed rather than the sea, and where the shape came from. ADR 0012's
          rule is that prose says whether a number is current; the same obligation applies to a
          picture, and this one is not current at all — it is permanent. */}
      <p className="map-slot-note">
        The sea floor, from <strong>GEBCO soundings</strong> — the Nazaré Canyon reaching almost to
        the beach. Depth only: nothing here is today&rsquo;s sea.
      </p>
    </aside>
  );
}
