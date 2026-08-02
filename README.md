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
| **Inputs** | Open-Meteo Marine API — swell height, period, direction, wind. One model today. ADR 0003 calls for several independent wave models per date, using their disagreement as the uncertainty estimate; ticket #8 introduces that, so **no uncertainty estimate exists yet**. |
| **Training target** | *Planned, not yet built.* Significant wave height from Monican02, the Instituto Hidrográfico mooring 15km off Nazaré near the canyon head. Hourly from 2010, via the Copernicus Marine In Situ TAC. Fourteen usable seasons — coverage is uneven and two winters are missing entirely. No buoy data reaches the running system: it is analysed in `analysis/buoy_coverage/` and becomes a dataset in ticket #9. |
| **Calibration** | *Researched, not yet applied.* A hand-verified set of days confirmed as genuinely giant — contest days, ratified records — to establish what a predicted height actually means. Thirty-eight such days are sourced in `analysis/gold_days/`; ticket #12 fits thresholds to them. Until it does, the thresholds in use are an uncalibrated rule of thumb and the interface says so. |
| **Baseline** | The surf community's rule of thumb, implemented first and retained permanently as the benchmark any learned model must beat. Scored in [`analysis/backtest/`](./analysis/backtest/): across the four seasons where the Swell partition exists it catches 3 of 9 Gold Days and issues 5 Go Calls, and a single threshold — the 14 s minimum swell period — causes every miss. |

## Running it locally

Requires **Python 3.14** and **Node 26**, the versions CI runs and the ones pinned in
`.python-version` and `.nvmrc`. Paths below are Windows; on macOS or Linux the
interpreter is `.venv/bin/python` and the CLI scripts live in `.venv/bin/`.

Every command below is written to be run **from the repository root**. Where a block
changes directory it says so, and the next block starts from the root again.

```bash
git clone https://github.com/NXA13/NazareNow.git
cd NazareNow

# One virtualenv serves both the backend and the analysis scripts.
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e "backend[dev]"

cd frontend && npm install && cd ..
```

Fetch some conditions before starting anything — the API has nothing to serve until a
Pipeline Run has stored something, and says so with a 503 rather than inventing zeros:

```bash
.venv/Scripts/python.exe -m nazarenow ingest
```

That contacts Open-Meteo, keeps the raw responses, and writes the parsed readings to
`data/nazarenow.db` at the repository root. The path is anchored to the repository
rather than the working directory, so ingesting and serving cannot end up on different
databases — they did, and the API reported no conditions while holding a good row.

To keep it current without touching it, run the schedule instead:

```bash
.venv/Scripts/python.exe -m nazarenow schedule
```

That runs immediately and then on the forecast cycle, logging each run's outcome. A failed
run loses the run, never the schedule — Open-Meteo will be unreachable sooner or later,
and a system that dies on one bad fetch stops silently while the site goes on serving old
data. Nothing is written by a failed run, and once two whole cycles have passed without a
successful one, the interface says so at the top of the page rather than leaving a reader
to subtract timestamps.

Both intervals live in `backend/src/nazarenow/cycle.py`, and the figure the page shows a
user is sent by the API rather than written into the page — it was typed there as a
literal once, which a change of cadence would have silently made untrue.

Three hours, not six, on evidence: `best_match` at Praia do Norte resolves to
MeteoFrance's wave model, which publishes twice a day, so this keeps the site within
three hours of a published run instead of up to half an update behind. See
[`analysis/forecast_models/`](./analysis/forecast_models/). It buys freshness, not
accuracy.

Per ADR 0005 these are the only parts of the system that talk to a third party.

Then two processes, in separate terminals:

```bash
# Backend on http://127.0.0.1:8000
cd backend
../.venv/Scripts/python.exe -m uvicorn nazarenow.api:app --app-dir src --reload

# Frontend on http://localhost:5273
cd frontend
npm run dev
```

The frontend port is pinned with `strictPort`, so a clash fails immediately rather than
silently moving to another port. That matters: the backend's CORS list names this exact
origin, and a drifting port would break the app in a way neither test suite can catch —
both seams mock the boundary between them.

### Checks

Each suite runs with one command. These are exactly the checks CI runs on every push —
if all of these pass locally, CI will pass too.

**Backend** (from the repository root):

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest
cd backend && ../.venv/Scripts/python.exe -m ruff check .
cd backend && ../.venv/Scripts/python.exe -m ruff format --check .
```

**Frontend** (from the repository root):

```bash
cd frontend && npm test
cd frontend && npm run typecheck
cd frontend && npm run lint
cd frontend && npm run format:check
cd frontend && npm run build
```

Prettier is configured with `endOfLine: auto`. Most files are LF in the working tree
because of `.gitattributes`, but any file written locally on Windows picks up CRLF, and
Prettier's default of `lf` then fails it while CI — which clones with LF — stays green.
That inversion trains people to ignore the check, so the setting removes it.

**Analysis scripts** — linted only. Running them needs Copernicus credentials and the
downloaded data, so CI checks them statically:

```bash
.venv/Scripts/python.exe -m ruff check analysis/
.venv/Scripts/python.exe -m ruff format --check analysis/
```

Two exceptions, both fully runnable because they need no credentials:

```bash
.venv/Scripts/python.exe analysis/gold_days/build.py --check
.venv/Scripts/python.exe analysis/backtest/swell.py --check
```

The Gold Day list is hand-written in `analysis/gold_days/README.md` and built from it into
`gold_days.jsonl`, which #12 calibrates against. `--check` fails if the two have drifted and
enforces the sourcing protocol — a missing quote, a missing publication date, a `Documented`
entry resting on a single source. A Gold Day recorded on weak evidence does not add noise;
it silently moves the threshold that decides whether someone is told to book a flight.

The second self-tests the arithmetic behind the backtest's Combined Sea to Swell
reconstruction — quantile mapping and bearings that wrap past north.

**The backtest itself** reads only free Open-Meteo data, so it runs too, though it downloads
about 10 MB the first time:

```bash
.venv/Scripts/python.exe analysis/backtest/hindcast.py
cd analysis/backtest && ../../.venv/Scripts/python.exe backtest.py
```

[`analysis/backtest/`](./analysis/backtest/) is the benchmark of ADR 0006: what the
Heuristic Baseline would have called across 2011-2025, and what it would have missed.
Deliberately not part of any test suite — an assertion that fails when accuracy shifts
slightly gets disabled within weeks. `backend/tests/test_baseline_is_fixed.py` pins the
thresholds the committed report describes, so the report cannot silently stop matching the
rule.

### Known gaps

**Mobile layout has no automated protection.** jsdom has no layout engine, so the
frontend suite cannot measure it. It was verified by hand at 320, 360 and 390px — every
reading and all nine forecast days render, the page never scrolls horizontally, and the
hourly table scrolls inside its own box rather than the page. The CSS uses only fluid
units, but nothing stops a regression; a browser-driven test would close this.

**No conditions at Praia do Norte are predicted yet — only offshore ones are shown.**
Ticket #6 asks for "predicted conditions at Praia do Norte … not only Offshore
Conditions", and that criterion is *not* met. The Heuristic Baseline passes the offshore
Significant Wave Height through unchanged, so the number labelled as predicted is the
offshore figure. The interface says so on every call, but disclosure is not the same as
satisfying the requirement, and this is recorded as unmet rather than ticked.

It is deliberately not fixed here. Predicting what the canyon does to a swell is what the
learned model in #13 earns; the only way to produce a different number today would be to
multiply by an invented amplification factor, which is precisely the confident, plausible,
wrong number ADR 0006 and `CONTEXT.md` exist to prevent. Slice 1 therefore ships real
advice built on a real rule of thumb, and no prediction of the break itself.

**The site shows more than ticket #4 asked for.** The ticket enumerates seven readings;
ten are displayed, adding significant wave height, wave period and wave direction under
a *Combined sea* heading. Significant Wave Height is the Proxy Target the whole project
is built on (ADR 0002), so showing it seemed worth the deviation — but it is a
deviation, recorded here rather than left for a reader to notice. The footer also states
that wind and air temperature come from a different forecast cell than the swell
readings, which the ticket did not ask for but which would otherwise be misleading.

### No test contacts a third-party service

This is enforced rather than asserted, in both suites:

- **Frontend** — MSW runs with `onUnhandledRequest: 'error'`, so any request a test did
  not explicitly mock fails the test instead of escaping to the network.
- **Backend** — `backend/tests/conftest.py` blocks outbound socket connections for every
  test, allowing only loopback. Adding a third-party call inside a request handler, which
  ADR 0005 forbids anyway, fails the suite immediately.

## Documentation

- [`CONTEXT.md`](./CONTEXT.md) — the domain glossary. Deliberately opinionated about vocabulary,
  particularly the distinction between wave *face height* and *significant wave height*.
- [`docs/adr/`](./docs/adr/) — architecture decision records covering why the system is shaped
  the way it is, including the alternatives that were rejected and why.

## Status

Slice 1 complete. Current Offshore Conditions and a nine-day forecast are ingested from
Open-Meteo, stored, and displayed with hour-by-hour detail — and every day now carries a
**Watch**, **Go**, **Confirmed** or **No call**, with the conditions that produced it.
Every call is kept: the store appends rather than replaces, so the succession of calls
made about a date as it approaches survives, which is the record #11 scores.

Each Pipeline Run is recorded in its own right, and the raw responses it fetched and the
calls it derived both point back at it — so the inputs behind any stored call are a
lookup rather than a guess about which fetch happened nearest in time. Runs that **fail**
are recorded too, with what kind of thing went wrong: a provider being unreachable and a
payload this system no longer understands are the same word in a log and need opposite
responses. A run that begins and never finishes stays marked `running`, which is how a
host that died mid-run shows up afterwards.

The Amplification Model behind those calls is the Heuristic Baseline of ADR 0006: the
surf community's rule of thumb, with no machine learning in it. It ships as the
permanent benchmark a learned model must beat in #13, and the interface says plainly
that its thresholds are not yet calibrated — #12 fits them to Gold Days.

The tiers are decided by Lead Time alone for now. ADR 0003 has them driven by Model
Spread — disagreement between independent wave models — which ticket #8 introduces; a
Watch is kept looser than a Go Call in the meantime by not requiring the wind
condition, and nothing claims the forecast has converged, because nothing measures it.

It predicts Significant Wave Height, not Face Height. The canyon's famous threefold
amplification applies to the wave a surfer rides; multiplying the instrument's measure
by a face-height factor would produce a confident, plausible, wrong number.

The baseline applies no amplification at all: the height it "predicts" is the offshore
forecast's own figure, carried through unchanged, and the interface says so on every
call. That is not an oversight — it is the floor #13's learned model has to clear, and
inventing a multiplier would have made the benchmark meaningless as well as wrong.

The range is nine days rather than sixteen because that is where the provider stops
modelling swell. It pads its time axis to whatever is requested and nulls the hours it
cannot fill; those hours are dropped rather than stored, since a null has no honest
rendering and a zero would draw a flat calm sea.

## Acknowledgements

Wave forecasts from [Open-Meteo](https://open-meteo.com). Buoy observations from the
[Instituto Hidrográfico](https://monican.hidrografico.pt)'s MONICAN network, via the
[Copernicus Marine Service](https://marine.copernicus.eu) In Situ TAC, with platform
discovery through [EMODnet Physics](https://emodnet.ec.europa.eu/en/physics).
