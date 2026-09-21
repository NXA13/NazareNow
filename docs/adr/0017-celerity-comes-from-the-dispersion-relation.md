# Celerity comes from the dispersion relation, not from a clamped shallow-water formula

The spec, the tickets and the prototype all name the same celerity law, and #122 shipped it:

```
c = min( gT / 2π , √(gd) )
```

**It cannot produce the picture this map exists to produce, and the first build of #122 proved
it.** Every test passed — the physics tests, the parity test against the reference
implementation, 484 unit tests and 25 layout tests — and the map drew a set of ruled diagonal
lines with no bend in them.

## Why the old law could not work

That formula is *exactly* deep-water celerity for every depth below `c_deep²/g`, and then
switches abruptly to the shallow-water form. At a 13.75 s period that switch is at **47 m**.

The Nazaré shelf is 100–200 m. The canyon is over 1000 m. **Under that law they run at
identical speed** — and the contrast between them is the entire reason a front bends. Nothing
could refract until the wave was inside the 47 m contour, which hugs the shore.

The real dispersion relation has no such step:

| depth | `min(c_deep, √(gd))` | `ω² = gk·tanh(kd)` |
|---|---|---|
| 226 m | 1.000 × c_deep | 1.000 |
| 148 m | 1.000 | 0.996 |
| 100 m | 1.000 | **0.975** |
| 80 m | 1.000 | 0.947 |
| 60 m | 1.000 | 0.892 |
| 47 m | 1.000 | 0.834 |

Two and a half percent, over forty kilometres of shelf, is the bend. The old law rounds it to
zero.

Measured on the real sea floor, frame by frame: the median crest bowed **7.85 view units** under
the old law and **10.96** under this one, and the largest bow went from 25.71 to 43.74.

## How it is solved

`ω² = gk·tanh(kd)`, by Newton from a `κ = x / √(tanh x)` start, where `x = ω²d/g`. That reaches
machine precision in three steps; four are taken. Checked against bisection over 77 depth and
period pairs: worst relative error **1.3 × 10⁻¹⁵**.

`prototypes/v2-map/refraction.py` runs the identical iteration from the identical start, because
the two implementations must agree to the last decimal — `refraction.parity.test.ts` is what
says so, and it compares every vertex of every crest.

## The bright band changed with it

Crests are drawn dim in deep water and bright where the swell has begun to bend. That boundary
was "half the deep-water wavelength", the textbook line for where a wave starts to feel the
bottom. **It is useless for drawing**: at that depth the front is still at 99.6% of its
open-ocean speed, and at a 17 s period the contour swallows most of the frame — 31 of 33 crests
came out bright and the distinction said nothing at all.

The boundary is now **where the front has actually slowed by 5%**, found by bisecting the
celerity function itself. It moves with the period for the same reason the bending does, rather
than tracking a contour that has no relationship to what the model is doing. At 13.75 s it lands
near 80 m. On the same frame the split went from 2 dim / 31 bright to **16 dim / 25 bright**.

## And the spacing

`CREST_SPACING` went from 38 view units to **58**. At 38 the frame carried 33 fronts, which read
as diagonal hatching and buried the canyon — the one shape the map exists to show, and the one
whose absence got the first map design rejected outright. The spacing was always arbitrary: the
true spacing over this frame is about 160 crests and a moiré pattern, which is *why* the
exaggeration has to be stated wherever the map is explained. It is chosen for legibility, and
legibility here means the sea floor still showing through.

## What did not change

The model is still **refraction alone**. It still ignores diffraction, reflection, currents and
non-linearity, and a real swell is still a spread of periods and directions rather than the
single one drawn. **It is still not a spectral wave model and must never be described as one.**
Using the correct dispersion relation makes it a better picture of refraction; it does not make
it a model of the sea.

## Consequences

- The solve does four Newton steps per wet cell, about 44,000 `tanh` calls per field. Measured
  rather than assumed: the whole pipeline was **52.9 ms** before this change and is **46.5 ms**
  after it. It got *faster*, because the wider crest spacing means fewer isochrone levels to
  trace and that saves more than the Newton iterations cost.
- **`crests.json` is regenerated**, and the reference implementation changes with the port. That
  file is a fixture, not an output: it is regenerated only when the *model* changes, and this is
  such an occasion.
- **A test now fails if the celerity law goes flat again**: it asserts that a 100 m shelf runs
  slower than open ocean, and that the speed falls monotonically with depth with no flat step.
  That is the assertion the first build of #122 lacked, and its absence is why a broken model
  shipped through a green suite.
- Spec §5's formula is amended to match. The old one is quoted there as what it was.
