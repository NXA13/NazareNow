# The refraction solve runs in the browser, and there are no crest bins

The v2 spec settled on 2026-09-18, while the tickets were written, that the refraction solve is
too heavy to run per request, so **crest fields are precomputed at build time for binned swell
period and direction, and the page picks the bin nearest the latest conditions**. #122 inherited
one open question from that: how finely to bin. The spec deliberately left it open and required
that *"the bin resolution, and the bytes it costs, are written down in the pull request"*.

Measuring it to answer that question is what killed the approach. **The solve now runs in the
browser, against the live period and direction, and no crest field is precomputed or shipped at
all.**

The spec's premise was never wrong — the solve is far too heavy to run *per request*, on a
Raspberry Pi, for every visitor. It is simply not too heavy to run **once per visitor, on the
visitor's own machine**, and nobody checked which of those two the sentence ruled out.

## The measurement that decided it

The bins have two axes and they behave nothing alike. Error here is the rotation of the wave
fronts — the orientation of the travel-time gradient, cell by cell — which, unlike the distance
between crest lines, is free of both the crest spacing and the animation phase:

| direction offset | front rotates by | | period offset | front rotates by |
|---|---|---|---|---|
| 2.5° | 2.38° | | +1 s | 0.58° |
| 5° | 4.74° | | +2 s | 1.23° |
| 10° | 9.35° | | +4 s | **2.56°** |
| 22.5° | 19.82° | | +6 s | 4.19° |

**A four-second period error bends the swell less than a three-degree direction error does.** The
spec's hint that *"at this scale a 13 s swell and a 13.75 s swell bend indistinguishably"* is
correct and is an understatement; what it does not say is that the direction axis has almost no
such forgiveness. A direction bin passes its own width through to the screen nearly undamped.

So the bins cannot be coarse where it counts. At 10° over the roughly 180° of open-ocean sector
that can reach the beach, against three period bins, that is 54 fields. One field costs
**5.60 kB** gzipped once simplified to tolerance 2.0 and rounded to integer view units — down
from the prototype's 11.82 kB, measured across a sweep of 108 encodings. Fifty-four of them is
**302 kB**, against a site that is allowed 130 kB in total.

## Why that is fatal rather than merely expensive

302 kB cannot be bundled, so binning forces the fields to be fetched one at a time — and then
`check-payload.mjs` has to stop summing everything in `dist/`, because it would count all 302 kB
against a visitor who downloads 5.60 kB of it.

That check is not incidental. Its own note says the budget *"exists to make a regression visible,
not to be a target to fill"* and sits where it does so that *"pulling in a charting or date
library — the usual way a page of this size doubles — fails here"*. Teaching it to ignore a
directory of lazily-fetched assets is exactly the hole a charting library would later walk
through. **The binned design cannot be built without weakening the one guard that makes the
budget mean anything.**

## What replaces it

Ship the **depth grid** — the soundings the solve reads — once, and solve in the browser for the
exact period and direction the conditions report.

| | |
|---|---|
| depth grid, int16 deltas at 1 m, gzipped | **9.35 kB** |
| full pipeline in the browser: solve, isochrones, joining, simplify, SVG | **52.9 ms** |
| of which the Dijkstra solve itself | **2.7 ms** |
| crest fields shipped | **none** |
| quantisation error | **none** |

One field for every possible sea, for less than a single binned field at the prototype's
fidelity. The page already waits on `/api/conditions/current` before it could draw a crest under
either design, so the 52.9 ms lands after a network round trip that has already happened.

**1 m and not 5 m.** Quantising the grid to 5 m would cost 5.65 kB instead of 9.35. It was
rejected: celerity is `√(gd)`, so in 10 m of water a 5 m quantum is a 50% error in wave speed,
and it falls in the shoaling zone — the bright part, the part the map exists to explain. Removing
one quantisation by introducing a worse one in the only place it matters is not a saving.

## The port is verified, not assumed

The browser port is checked against `prototypes/v2-map/refraction.py`, which stays as the
reference implementation:

- the travel-time field is **bit-identical** across all 10,900 wet cells — worst difference
  `0.00e+0` seconds;
- the drawn output is the same **364 paths** with the same vertex counts, and the worst
  coordinate difference anywhere is **0.1 view units** — one unit in the last printed decimal,
  because Python rounds halves to even and JavaScript rounds them away from zero. 0.08 px.

A test pins this, so a future edit to either side that changes the physics fails rather than
quietly drawing a different sea.

## The metric that does not work, recorded so it is not tried again

The obvious way to measure a bin's error is the distance between the crest lines it draws and the
crest lines the true conditions would draw. **It cannot work, and it fails silently.** Crests are
a family of near-parallel lines about 38 view units apart, so nearest-crest distance is bounded
by half the spacing and saturates at a quarter of it for any perturbation beyond a hair. Measured
that way, a 2.5° direction error and a 30° direction error both score ≈ 8.9 units:

```
direction + 2.5 deg   mean 7.25 u      direction +15 deg   mean 8.90 u
direction + 5.0 deg   mean 8.53 u      direction +30 deg   mean 8.97 u
```

Optimising the animation phase out of it does not rescue it; the control case reads 0.00 and the
saturation stays. It is a plausible-looking number that carries no information, which is worse
than no number. Front orientation is the metric; crest distance is not.

## Considered and rejected

- **Keep the bins and accept coarse direction.** At 22.5° bins the fronts can point nearly 11°
  wrong, on a map whose whole claim is that the shape is computed rather than drawn. The one
  thing the map must get right is the direction the swell arrives from.
- **Bins as lazily-fetched assets.** The design binning forces, and the reason it is fatal: see
  above. It also adds a second round trip to first paint of the crests.
- **Ship the travel-time field per bin instead of the crest paths.** Still per bin, and larger
  per bin than the crests are; it inherits every problem above and adds marching squares to the
  client anyway.
- **Solve on the backend per request.** What the spec's original sentence actually ruled out, and
  it is still ruled out: v2 is one backend ticket (#120, merged), the host is a Raspberry Pi, and
  a per-request Dijkstra is exactly the load a static site should not take.

## Consequences

- **The payload budget moves, and the figure is measured in the same commit**, as it was for the
  fonts (#114) and the sea floor (#121). The depth grid measures 9.35 kB gzipped standalone; what
  it costs *in the bundle* is measured by `check-payload.mjs` against a real build, never
  projected from the standalone figure.
- **`check-payload.mjs` keeps counting everything in `dist/`.** Preserving that is one of the
  reasons this decision went the way it did.
- **#122's acceptance criterion about bin resolution is satisfied by recording that there are no
  bins,** and the ticket is updated to say so rather than left to read as unmet.
- **The two honesty statements are unchanged and matter more, not less.** The crest *shape* is
  computed and the *spacing* is exaggerated; the model is refraction alone, ignoring diffraction,
  reflection, currents and non-linearity, and a real swell is a spread of periods and directions
  rather than one. A model that now runs live, on the visitor's machine, against this morning's
  conditions, is far more tempting to call a forecast of the surf. **It is not a spectral wave
  model and must never be described as one.**
- **`prototypes/v2-map/refraction.py` and its `crests.json` stop being a prototype and become the
  fixture the shipped code is tested against.** They must not be deleted or regenerated casually.
- The client does ~53 ms of work per load on this machine. That is measured here and not on a
  phone; if it ever matters, the solve moves to a worker, and the 2.7 ms Dijkstra says the cost
  is in the isochrones rather than the physics.
