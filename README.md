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
| **Training target** | Significant wave height from Monican02, the Instituto Hidrográfico mooring 15km off Nazaré near the canyon head. Hourly from 2010, via the Copernicus Marine In Situ TAC. Fourteen usable seasons — coverage is uneven and two winters are missing entirely. |
| **Calibration** | A hand-verified set of days confirmed as genuinely giant — contest days, ratified records — used to establish what a predicted height actually means. |
| **Baseline** | The surf community's rule of thumb, implemented first and retained permanently as the benchmark any learned model must beat. |

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

Two processes, in separate terminals:

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

**Analysis scripts** — linted only. Running them needs Copernicus credentials and the
downloaded data, so CI checks them statically:

```bash
.venv/Scripts/python.exe -m ruff check analysis/
.venv/Scripts/python.exe -m ruff format --check analysis/
```

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

In design. No implementation yet.

## Acknowledgements

Wave forecasts from [Open-Meteo](https://open-meteo.com). Buoy observations from the
[Instituto Hidrográfico](https://monican.hidrografico.pt)'s MONICAN network, via the
[Copernicus Marine Service](https://marine.copernicus.eu) In Situ TAC, with platform
discovery through [EMODnet Physics](https://emodnet.ec.europa.eu/en/physics).
