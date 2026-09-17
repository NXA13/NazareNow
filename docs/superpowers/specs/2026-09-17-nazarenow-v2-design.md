# NazaréNow v2 — design spec

Written 2026-09-17, from a brainstorming session with Nick. Every decision below was made by
him against something he could see; nothing here is inferred.

**Status:** design settled, implementation not begun. The next step is an implementation plan,
not code.

**Milestone:** v2 — *dynamic coastline map with live conditions* (GitHub milestone 2, currently
empty). Same repository, same application.

---

## 1. Why v2 exists

Nick's words, on seeing the running v1 site: it is impressive, but *"the site has a very basic
feeling — the colours, style and logo are very standard and feel outdated"*, and *"the page is
flooded with text, instructions and information … it takes away from the dynamic feeling and
purpose of the site."*

Both complaints are fair and they are the same complaint twice: the page is a correct instrument
that does not feel like the thing it is about. v2 does three things about it.

1. **Simplify the home page** to the live picture and the verdict.
2. **Add the dynamic map** the roadmap has always promised — the canyon, with swell and wind on
   it, moving.
3. **Move the explanations to a second page**, without demoting the limits that qualify a
   number.

This is a re-skin plus one genuinely new subsystem. The backend's decision-making is untouched.

---

## 2. What the pages are

### Home — the forecast

In order down the left column, with the map filling the right:

1. **The verdict.** "Book for Sun 20 Sept", with the call's lead time, the predicted significant
   wave height, the plausible range, and whether the wave models agreed.
2. **Four condition tiles** — significant wave height, swell period, swell direction, wind speed.
3. **The next N days**, one day per row.
4. **The hour-by-hour panel**, which replaces the day list in the same slot when a day is
   clicked.
5. **One line of track record**, linking out.

### How it works — everything else

The whole track record with its two panels and its limitations prose, the six-gate chain, how
the canyon works, how the Predictive Distribution was calibrated, the Face Height versus
Significant Wave Height distinction, ADR 0012, the Proxy Target.

### The rule that governs the split

**Limits that qualify a number stay beside that number. Teaching material moves.**

The modelled-not-measured provenance, the range-runs-wide admission, the extrapolated-past-day-7
caution and the height-only caveat on the probability all stay on the home page, attached to the
figures they qualify. The explanation of *how* any of it was computed moves.

This rule exists because a redesign is exactly the change that quietly turns a disclaimer into
elegant grey 11px fine print, and the project exists to avoid overclaiming. Treat "the limits
stay as prominent as the numbers" as a requirement with the same standing as any other.

### The four tiles, and the six readings that are not on them

Settled 2026-09-17, after the spec was written. `/api/conditions/current` sends ten readings and
the design shows four tiles, and the four are not an arbitrary selection: they are exactly the
quantities a Go Call is gated on. That is the rule — **the tile row is what the call is decided
on, at the size of a headline.**

The other six are not dropped. **Each tile carries the rest of its own wave field, small.**

| Tile | The number | What rides with it |
|---|---|---|
| Significant Wave Height | the gated height | `wave_period`, `wave_direction` — this tile *is* the Combined Sea |
| Swell period | the gated period | `swell_height`, which keeps the Swell's own height visibly apart from the combined figure above |
| Swell direction | the gated bearing | degrees and a compass point, as today |
| Wind speed | the gated speed | `wind_direction`, as a compass point with the same dart glyph the map uses |

The two temperatures gate nothing, so they take **one quiet line under the tiles** — "Sea 16 °C ·
Air 19 °C". They were nearly declared unread, and were not, because the pipeline would then go on
fetching and storing two numbers the site never shows, which is worse than one short line.

The effect on `every-field-is-read.test.tsx` is the point of doing this deliberately: all sixteen
fields of `CurrentConditions` stay in the registry's *read* arm, so the rebuild never has to
argue a field onto the "not read" list under test pressure.

---

## 3. Layout

**Two columns, equal height, nothing scrolls on desktop.** The forecast column on the left, the
map on the right, the map matching the column's height rather than being pinned or sticky.

The map is not fixed and the left column is not independently scrollable. Both were considered
and rejected: a fixed map with content sliding past it is Windy's solution, and it reads as two
unrelated panels rather than one instrument.

**The hour-by-hour panel takes the day list's slot** rather than opening beneath it. This is what
makes "equal height, nothing scrolls" survive someone clicking something: the column's height
never changes, so the map's aspect ratio never changes. The cost, accepted knowingly, is that
the day list and the hours cannot be seen at once.

**No-scroll is a desktop promise only.** The phone layout is a separate design, not a
consequence of this one. Story 26 (phone layout) has never been verified in this repository and
must not be assumed to fall out of the desktop work.

### The day list

**One day per row**, not a grid. Each row carries the date, the height, a comparison bar and the
status — a grid cell fits two of those three.

**The number of days is the provider's, not ours.** Nothing in the code chooses eleven:
`open_meteo.py` requests `FORECAST_DAYS = 16` and the page renders whatever the merged marine
and weather forecasts actually cover, which is currently about eleven. It could return ten, or
eight if the provider shortens its horizon. **Any layout that assumes a fixed count is a layout
that breaks silently**, which is this project's characteristic failure mode.

**There is a real boundary at day 7** and the design uses it: the measured forecast-error archive
covers seven days, and past that the plausible range is extrapolated rather than measured. Days
beyond seven sit below a divider, dimmed, under "Beyond the measured archive". This was chosen
over trimming the list to a round number — that would have hidden a day someone could still book
a flight for, to make the arithmetic neat.

---

## 4. The visual system

Direction **Ink**: a near-black neutral graphite ground, Space Grotesk for text, IBM Plex Mono
for every number.

### Three colour systems, deliberately kept apart

| System | Colour | Carries |
|---|---|---|
| **Status** | pastel green `#a6dfae` (Go), pastel yellow `#ecdc9a` (Watch) | A state of the sea. Day rows, the verdict panel. |
| **Main** | Ice, `#8ecfe6` | The wordmark, the nav, links, and the swell crests on the map. |
| **Wind** | neutral warm grey `rgba(206,202,194,0.85)` | Wind only, and deliberately quieter than the swell. |

The main colour went onto the swell crests for a reason worth recording: with the statuses
pastel, it had nothing left to do but tint a wordmark, and three variants differing only in a
logo tint are not a choice. Putting it on the swell also keeps the governing rule intact —
**the base map is greyscale; colour means live data.**

The verdict panel takes the *status* colour, not the main colour, so the brand never competes
with the call for attention.

### One known trade, accepted

Pastel green is a calmer Go Call than the vermilion it replaced. It still reads because it is
light on near-black, but the loudest thing on the page is now a soft green rather than an alarm,
and green conventionally means *safe* while a Nazaré Go Call means a giant and dangerous swell is
coming. Nick chose this knowing it. **If it ever reads as too relaxed, the fix is more weight or
size on the Go row, not more saturation** — saturating it would break the colour system above.

---

## 5. The map

### What it is made of

**Real bathymetry.** 12,826 GEBCO 2020 depth soundings over 39.40–39.82°N, 9.04–9.52°W at 15
arc-seconds, traced into contours by marching squares and simplified with Douglas-Peucker to
about 20 kB of SVG path data. Depth is drawn as stacked tonal bands, shallow to deep, with
hairline contours over them.

Nothing on the map is illustrated. The Berlengas, two seamounts and the Lagoa de Óbidos appear
because they are in the soundings.

The first attempt drew the canyon by hand and was rejected outright: *"the map designs are
terrible. Very basic, and the canyon can't be seen, which was a main request."* The lesson
generalises — **the canyon is the one shape on earth that makes Nazaré Nazaré, and it must come
from data.**

### The waves bend

Wave crests are **isochrones of a refraction model** solved over the depth grid:

```
c = min( gT / 2π , √(gd) )
```

travel time by Dijkstra with eight neighbours, cost = distance / celerity, seeded with a straight
plane wave on the upwind edges. The fronts therefore bend, stall and wrap the headland for the
same reason real ones do: the canyon stays deep and fast while the shelf either side slows the
wave, and the energy converges on one stretch of beach.

Crests are drawn twice — dim over deep water, bright inside the shoaling zone (shallower than
half the deep-water wavelength, about 155 m for a 13.75 s swell), which is exactly where the
bending begins.

**What must always be stated where this is shown:** the *shape* is computed; the *spacing* is
exaggerated, because a 13.75 s swell has a 295 m wavelength and the true spacing over this frame
is 160 crests and a moiré pattern. And the model is refraction alone — it ignores diffraction,
reflection, currents and non-linearity, and a real swell is a spread of periods and directions
rather than one. **It is not a spectral wave model and must not be described as one.**

**Where the solve happens, settled 2026-09-18 while the tickets were written.** The refraction
solve is too heavy to run per request, so the crest fields are precomputed at build time for
binned swell period and direction, and the page picks the bin nearest the latest conditions.
This keeps v2 to a single backend ticket. The honest cost is that the crests are quantised, so
the bin resolution is written down beside the bytes it costs — and at this scale a 13 s swell
and a 13.75 s swell bend indistinguishably, which is what makes the quantisation acceptable
rather than merely convenient.

### Wind

**Sharp darts, one per forecast grid point**, pointing downwind and drifting along their own
heading at `33 / speed` seconds per hop. Faster wind, faster drift.

Darts were chosen over flowing streaks for an honesty reason as much as an aesthetic one: the
map's wind comes from roughly twenty to thirty sampled points, and a continuous flow would imply
a field we do not have. One dart per fetched point is literally what the data is.

Comets (a tail whose length encodes speed) and meteorological wind barbs were both built and
rejected. The known cost of darts: **speed lives entirely in the motion, so a still frame of the
map does not show it.** If that ever matters, comets are the fix and the code for them is in the
prototype.

The legend shows the same glyph at 10, 25 and 45 km/h drifting at their real rates, built from
the same function the map uses so the legend cannot disagree with the map.

### What the map needs that the backend does not yet have

A grid. Today the pipeline stores **one** Open-Meteo point about 15 km offshore. The map needs a
grid of them, fetched each Pipeline Run and stored, with a new read endpoint to serve them.

**Extent, settled 2026-09-18:** 25 points, 5 by 5, over exactly the frame the map draws —
39.40–39.82°N, 9.04–9.52°W. Sharing the bathymetry's bounds rather than choosing new ones means a
wind glyph can never appear outside the drawn map. Open-Meteo accepts several coordinates in one
request, so this is one request per run rather than twenty-five.

**Scope decision: latest conditions only.** No time scrubber, no per-day fields. One grid
snapshot per run. A scrubber can be added later without redesigning anything — the endpoint
simply gains hours — and was rejected now because it multiplies stored bytes by the forecast
horizon for a feature nobody has asked to use.

---

## 6. Constraints that bind the implementation

**Payload budget rises from 95 kB to about 140 kB gzipped.** `frontend/scripts/check-payload.mjs`
counts every file in `dist/`, images included, and its own comment requires that the budget move
"in the same commit, with the reason written down". That commit is part of this work. The rise
buys real GEBCO contours; it does not buy a component library, an icon set, a charting library or
a map library, all of which remain out of the question.

**Routing must be hand-rolled.** There is no router in the application today — `App.tsx` renders
`TrackRecordPage` inline. React Router costs about 20 kB gzipped and would consume most of the
increase on its own. A hash router of roughly 1 kB matches both the budget and the codebase's
dependency-free habit.

**Domain vocabulary is governed by `CONTEXT.md`.** The Face Height versus Significant Wave Height
distinction is load-bearing and cannot be blurred for readability. Any wording change that names
a domain concept goes through the domain-modeling skill.

**`frontend/src/every-field-is-read.test.tsx` (141 tests) fails if the redesign drops a field the
backend sends.** It is the guardrail that makes this safe; expect it to fail loudly and often
during the rebuild, and treat each failure as a question about where that field went rather than
a test to update.

**ADRs quote old names on purpose.** A scripted rename across `docs/adr/` corrupts the decision
record invisibly.

---

## 7. Out of scope

- Any change to the Decision Model, the Amplification Model or the Predictive Distribution.
- A time scrubber on the map.
- Face Height (story 13, unmet by design — see `CONTEXT.md` and ADR 0002).
- Deployment (#28, v3). The design settling is what #28 was waiting on, so the public half of
  that deployment unblocks when this ships.

---

## 8. Open questions

One is left.

1. **The wind bearing is not in the scenario data used for the mockups.** Only the speed was
   recorded, so 160° is a stand-in throughout the artboards. The live field carries a real
   bearing; nothing depends on this beyond the mockups.

The other two were settled and moved into the body of this spec rather than left here. Where the
six condition readings that are not tiles go is now §2; the wind grid's extent and spacing, and
where the refraction solve happens, are now §5.

**The work is ticketed.** Milestone 2 carries eleven issues, #113 to #123, with native blocking
edges between them. #113 (the router) and #120 (the conditions grid) have no blockers and can
start in parallel.

---

## 9. Where the evidence lives

- **Design canvas**, all artboards and decisions: <https://claude.ai/artifact/E5JDwvzHxY2z9R4bCiqEGV>
- **Map data pipeline**, working, with its own README and a list of the defects already found:
  `prototypes/v2-map/`
- **Scenario harness** that produced every real number in the mockups: `scenarios/`, built in the
  previous session. The `gold-day` scenario is a Go Call at lead time 4, models agreed, predicted
  6.42 m, plausible 4.28–8.79 m.
