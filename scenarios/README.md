# Scenarios

The site almost always shows the same screen. Most days at Praia do Norte are flat, so a
visitor — or a developer, or an interviewer — sees nine cards reading "No call" and a
headline saying nothing is worth booking. That is the correct answer, and a useless thing
either to learn from or to design against.

These build the screens that matter, from days that actually happened.

```bash
python scenarios/build.py --list          # what exists, and what each one teaches
python scenarios/build.py gold-day        # build one
python scenarios/build.py --all           # build all five

NAZARENOW_DB=scenarios/stores/gold-day.db \
  python -m uvicorn nazarenow.api:app --port 8000
# then, from frontend/, npm run dev
```

## What it actually does

It runs the **real pipeline**. Historical Open-Meteo payloads are reshaped into the form the
live endpoints return and served to `run_pipeline` through an `httpx.MockTransport`, so the
payload validation, the Amplification Model, the Predictive Distribution, the Decision Model
and every store write are the shipped code taking a real decision. Nothing here reimplements
a verdict and nothing fabricates one.

That is the whole point. If the system would not have called Go on a day, this produces no
Go — which is why `missed-gold-day` exists and is worth as much as `gold-day`. A demo rigged
to show only success would teach the wrong thing and be indefensible to explain to anybody.

By default the time axis is shifted so the scenario's issue date reads as today, which is
what puts the page in its live state rather than behind a staleness banner. The shift is
printed on every build, recorded in the scenario's `.json`, and `--real-dates` turns it off.

## The fidelity caveat

Open-Meteo's archive returns what the sea **did**, not the forecast as it was issued at the
time. So a scenario carries Hindcast conditions presented through the live interface —
exactly the distinction the track record already makes at length, and for the same reason.

A real forecast is less certain than this. Treat a scenario as the system at its best, not as
what it will do next winter. Open-Meteo's historical-forecast API would remove the caveat and
is the obvious upgrade if these ever need to be more than a teaching and design tool.

Two other limits worth knowing:

- **The marine archive begins in 2022** at this location. Earlier giant days cannot be built
  at all, including 18 January 2018 — a ratified Gold Day the system called Go on, and the
  scenario everyone reaches for first.
- **Every verdict is checked beforehand** against `analysis/backtest/output/daily_calls.csv`,
  so what each scenario should produce is known before it is built. A scenario that comes out
  differently is a finding worth chasing, not a mystery.

## The five

| Name | What it shows |
|---|---|
| `gold-day` | A Go Call at Lead Time 4 on 13 Dec 2025 — a ratified Gold Day that peaked at 5.30m. The screen a Traveller would have booked a flight from. |
| `confirmed` | The same swell one day out. Nothing left to book, so the system stops recommending and starts reporting. The sea is identical; the advice is not. |
| `flagged-not-gold` | A Go Call on a 5.17m day that appears in no Gold Day record. Why the published precision figure can only ever be an upper bound. |
| `missed-gold-day` | A ratified Gold Day the system only raised a Watch for. The failure that argues for the Watch tier existing. |
| `quiet` | An ordinary September. The baseline, and what the site shows most weeks of the year. |

`stores/` is generated and gitignored — each build fetches fresh and rewrites its database.

## Adding one

Find a day worth showing in `analysis/backtest/output/daily_calls.csv`, which holds 10,958
reconstructed days with the call the system would have made and the sea that arrived. Pick
the issue date from the Lead Time you want: a Go Call lives at 2 to 7 days out, a Confirmed
at 1 or less, and a Watch above 1. Then add it to `SCENARIOS` with a note saying what it
teaches, because a scenario nobody can explain the point of will not survive being
rediscovered in six months.
