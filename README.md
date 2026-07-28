# NazaréNow

Forecasts when Praia do Norte in Nazaré, Portugal will produce giant waves — early enough to
book a flight and actually see them.

## The problem

Nazaré's waves are the biggest surfed on Earth, and they are caused by an underwater canyon that
focuses Atlantic swell onto a single beach. The swell that produces them is visible in public
forecasts more than a week ahead. But by the time a swell is reported as news, flights and
accommodation are gone. The information arrives long before the decision is actionable, and
nothing turns one into the other.

## What this is, and what it isn't

This is **not** a wave forecaster. Predicting open-ocean swell is already solved to a standard
this project could not approach — ECMWF and NOAA run physics simulations that publish free
forecasts up to 15 days out, and those are consumed here as an input.

Those models run on a grid of roughly 50km. The Nazaré Canyon is invisible at that resolution.
So they can say what swell will arrive off the Portuguese coast, and they cannot say what the
canyon will do with it.

That gap is what this project models:

```
   ATLANTIC              THE CANYON            PRAIA DO NORTE

   4m swell     ────►    amplification  ────►  how big,
   16s period            (below global          actually?
   from WNW               model resolution)

   free, accurate        ← the model            the question
   already                 lives here           worth asking
```

A second layer turns that prediction into a decision — not "how big will it be" but "should you
book now, or wait for a better forecast?" — issued as tiered calls modelled on how national
weather services separate a *watch* from a *warning*.

## Approach

| | |
|---|---|
| **Inputs** | Open-Meteo Marine API — swell height, period, direction, wind. Multiple independent wave models queried per date; their disagreement serves as the uncertainty estimate. |
| **Training target** | Significant wave height from the Instituto Hidrográfico's MONICAN buoy off Nazaré, hourly since 2009, via EMODnet ERDDAP. |
| **Calibration** | A hand-verified set of days confirmed as genuinely giant — contest days, ratified records — used to establish what a predicted height actually means. |
| **Baseline** | The surf community's rule of thumb, implemented first and retained permanently as the benchmark any learned model must beat. |

## Documentation

- [`CONTEXT.md`](./CONTEXT.md) — the domain glossary. Deliberately opinionated about vocabulary,
  particularly the distinction between wave *face height* and *significant wave height*.
- [`docs/adr/`](./docs/adr/) — architecture decision records covering why the system is shaped
  the way it is, including the alternatives that were rejected and why.

## Status

In design. No implementation yet.

## Acknowledgements

Wave forecasts from [Open-Meteo](https://open-meteo.com). Buoy observations from the
[Instituto Hidrográfico](https://monican.hidrografico.pt) via
[EMODnet Physics](https://emodnet.ec.europa.eu/en/physics).
