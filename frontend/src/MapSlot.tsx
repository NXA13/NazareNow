/**
 * Where the map will go, and visibly not a map (#115).
 *
 * The right column exists before its contents do, so the shell's promises — two columns of equal
 * height, a stable split, nothing scrolling on desktop — can be tested before there is anything
 * expensive inside it. That is the whole reason this ticket comes first.
 *
 * **It must not pretend.** No grey landmass, no fake contours, no plausible-looking coastline: a
 * placeholder that resembles the thing it stands in for is how a half-built feature gets
 * mistaken for a finished one, and this project's characteristic failure is a page that claims
 * more than it has. So it says what it is, in words, and says what will replace it.
 *
 * The real map is #121 (the canyon, traced from soundings), #122 (swell refracting over it) and
 * #123 (wind). It is drawn as SVG that fits whatever box it is given, which is why this slot is
 * a box with no aspect ratio of its own on desktop: it takes the height of the column beside it.
 */

export function MapSlot() {
  return (
    <aside className="map-slot" aria-label="Map">
      <p className="map-slot-what">Map</p>
      <p className="map-slot-note">
        The canyon, the swell bending over it and the wind across it are drawn here. Not built yet —
        this is a placeholder holding the space, so the page around it can be measured first.
      </p>
    </aside>
  );
}
