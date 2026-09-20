# The whole map frame is drawn, and the panel letterboxes rather than the frame cropping

The map (#121) is one fixed view of one fixed place: a 686.8 × 780.0 viewBox over
39.40–39.82°N, 9.04–9.52°W, traced from soundings. The panel it sits in takes its height from
the forecast column beside it, which is content-driven, so the slot's aspect ratio does not match
the frame's and cannot be made to. Something has to give. The choice is `preserveAspectRatio`:
crop the frame to fill the panel (`slice`), or fit the whole frame and leave part of the panel
unpainted (`meet`).

It shipped as `xMidYMid slice`, and `App.css` carried the argument for it: *"Cropping keeps the
canyon head — the part of this map anybody is looking at — filling the space it is given."*

**It is now `xMidYMin meet`.** The argument above was made against an estimate, the estimate was
wrong, and the true number changed which option wins.

## The measurement

At the 1440×900 desktop viewport, read out of a browser through the SVG's CTM rather than
computed:

| | |
|---|---|
| `svg.bathymetry` element box | 574.67 × 750.05 px (aspect 0.7662) |
| viewBox | 686.8 × 780.0 (aspect 0.8805) |
| `slice` | scales ×0.9616 → 660.42 px wide, **42.88 px off each side**, nothing top or bottom |
| `meet` | scales ×0.8367 → 574.67 × 652.66 px, **97.39 px of letterbox**, nothing left or right |

42.88 px is **44.59 viewBox units, 6.49% of the frame's width each side — 12.98% in total.** The
previous handoff estimated "~20%". The real figure is smaller, and that is exactly why it was
worse.

## Why the smaller number was the more serious problem

`open_meteo.grid_points()` (#120) divides the frame by `GRID_SIDE - 1`, so the outer columns of
the wind grid land on the bounds themselves — 9.52°W and 9.04°W — as endpoints rather than as
cell centres. In viewBox terms they sit at x=0 and x=686.8.

A crop of 44.59 units each side therefore does not shave edge detail. **It takes the first and
last columns whole: two of five, 10 of the 25 points, 40% of the wind field.** The next columns
in are at 9.40°W and 9.16°W, far enough inside to be safe — so the loss is precisely two columns,
not a gradient.

That collides with two commitments that were made deliberately and in writing:

- **The spec's reason for choosing darts over a continuous flow is honesty about sample count:**
  *"the map's wind comes from roughly twenty to thirty sampled points, and a continuous flow
  would imply a field we do not have. One dart per fetched point is literally what the data is."*
  A crop that silently deletes 40% of the darts breaks that claim in the exact way darts were
  chosen to avoid — the map would show a field, and it would not be the field that was fetched.
- **`open_meteo.py` states a guarantee that `slice` quietly voids.** The grid shares the
  bathymetry's bounds so that *"a wind glyph placed from a grid point can then never sit outside
  the drawn map, because there is no grid point outside it."* Under `slice` that stays literally
  true and stops being useful: the glyph is inside the drawn map and outside the *visible* one.
  A guarantee whose premise is that the frame is all shown needs the frame to be all shown.

Neither would have failed a test. Both would have looked like the map working.

## `YMin`, not `YMid`

The 97.39 px has to go somewhere. `YMid` splits it into two ~48.7 px bands, and a gap above the
map reads as a rendering fault rather than as a decision. `YMin` puts the map flush to the top of
its panel and collects the whole band underneath, directly above the caption, where it reads as
caption spacing.

## The band stays the panel's background

**It is not filled with `--map-band-7`**, the deepest tone, and this is the part most likely to
be "fixed" later. The letterbox falls at the frame's north and south edges — open ocean and
coast. Extending the deepest tone into them would draw sea floor that was never surveyed, which
is the same objection that got the hand-drawn canyon rejected outright: nothing on this map is
illustrated. Unpainted panel is honest; invented bathymetry is not.

## Considered and rejected

- **Re-cut the frame to the panel's proportion.** This is the only option that avoids both a crop
  and a band, and it is the most expensive: the contours are traced from 12,826 GEBCO soundings
  which must not be re-fetched, and the panel's aspect ratio is not a constant to cut against —
  it follows the forecast column's content and moves with the number of days.
- **Crop, but move the grid inward to cell centres.** This keeps the panel full and keeps all 25
  darts visible, and it was rejected because it solves the symptom by making the grid stop
  covering the frame. The bounds are shared with the bathymetry on purpose, and #120's extent
  decision would have to be reopened to buy back 12.98% of a panel.

## The narrow layout pays nothing, and that was measured rather than assumed

A first draft of this ADR reasoned that at a slot proportionally wider than 0.8805 the letterbox
would flip to horizontal. Measured at 390×844, it does not flip, because there is nothing to
flip: the map's box is **356 × 404.30 px, a ratio of 0.8805 — the frame's own** — and the drawing
fills it corner to corner. The panel's height is content-driven there rather than set by a column
beside it, so it takes the frame's proportion instead of imposing one.

So the letterbox is a desktop cost only, and the phone layout — which #115 explicitly does not
design — is unaffected by this decision in either direction.

## Consequences

- `e2e/layout.spec.ts` grows an assertion that the rendered content box lands inside the element
  box, measured through the CTM. **The existing test could not see any of this**: the `<svg>`
  *element* fills the slot identically under both values, so "the drawing fills the slot" passed
  against a drawing with 40% of its wind data off the edge. A silent return to `slice` now fails.
- The panel is ~13% less full at desktop, which was the cost `slice` was chosen to avoid. It is
  paid knowingly, and #122 and #123 can now promise that every point they fetch is a point a
  reader can see.
- No data, no geometry and no bounds change. Only which part of the frame reaches the screen.
